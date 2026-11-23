"""Avaliação dos agentes: perguntas com resposta conhecida, corrigidas em código.

Mede duas coisas, separadas de propósito:
  * ACERTO   — a resposta traz o que precisa trazer (nomes, valores, datas) segundo evals/casos.json;
  * INVENÇÃO — a resposta cita recurso ou valor em R$ que NÃO saiu das ferramentas (alucinação).

Uso (na raiz do projeto, com o Docker Desktop aberto):
  python evals/avaliar.py                                   # modelo do YAML (qwen3 local)
  python evals/avaliar.py --modelo dmr/ai/gemma3            # compara com outro modelo (docker model pull antes)
  python evals/avaliar.py --so finops --repetir 3           # só uma equipe, 3 vezes cada pergunta
  python evals/avaliar.py --corrigir respostas.json         # só corrige respostas já salvas (sem rodar modelo)

Resultados em evals/resultados/ (um .json e um .md por rodada) e a tabela comparativa em evals/resultados/RESUMO.md.
Termina com "RESULTADO: AVALIAÇÃO CONCLUÍDA" (ou "RESULTADO: ERRO ...").
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASOS = ROOT / "evals" / "casos.json"
SAIDA = ROOT / "evals" / "resultados"
PY = sys.executable
EQUIPES = {"finops": ROOT / "agents" / "finops.yaml", "documentacao": ROOT / "agents" / "documentacao.yaml"}
# ferramentas que a avaliação deixa o agente usar sem perguntar (--safety restricted nega todo o resto).
# sincronizar_azure fica de fora: precisa de login no Azure e não faz parte das perguntas.
PERMITIDAS = {
    "finops": ["resumo_custos", "detectar_anomalias", "detalhar_recurso", "gerar_relatorio", "clientes_resumo",
               "cliente_detalhe", "economia_cliente", "relatorio_executivo_cliente", "transfer_task"],
    "documentacao": ["listar_logicapps", "resumo_logicapp", "achados_boas_praticas", "comparar_versoes", "gerar_documentacao",
                     "transfer_task"],
}
TOLERANCIA = 0.011

# nomes que parecem recurso de nuvem: prefixos usuais do Azure (e da AWS, que o modelo já inventou antes)
PREFIXOS = ("vm", "stg", "st", "func", "fn", "lgc", "la", "sqldb", "sql", "db", "apim", "appi", "kv", "rg", "aks", "acr",
            "app", "web", "cosmos", "redis", "nsg", "vnet", "pip", "lb", "disk", "ec2", "s3", "bucket", "lambda", "rds")
RE_NOME = re.compile(r"(?<![\w.@/-])([a-z][a-z0-9]*(?:-[a-z0-9]+)+|stg[a-z0-9]{3,}|ec2|s3)(?![\w-])")
RE_REAIS = re.compile(r"R\$\s*(-?[\d.,]*\d)")
RE_NUMERO = re.compile(r"(?<![\w])-?\d[\d.,]*")


# ferramenta "escrita como texto": o modelo devolve `transfer_task(...)` na resposta em vez de chamar a ferramenta.
# Acontece com modelo sem suporte a chamada de ferramentas no Docker Model Runner (ex.: gemma3) ou pequeno demais.
FERRAMENTAS = sorted({f for fs in PERMITIDAS.values() for f in fs} | {"sincronizar_azure"})
RE_CHAMADA_TEXTO = re.compile(r"(?i)```tool_code|\b(?:" + "|".join(FERRAMENTAS) + r")\b\s*[({]")


def chamada_em_texto(resposta):
    return bool(RE_CHAMADA_TEXTO.search(resposta or ""))


# ------------------------------------------------------------------ normalização
def sem_acento(t):
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t.replace("_", " "))  # SEM_TRATAMENTO_DE_ERRO conta como "tratamento de erro"


def para_numero(txt):
    """'1.615,92' / '1615.92' / '732' / '732,00' / '2.2' -> float (None se não der)."""
    t = txt.strip().rstrip(".,")
    if not t or not any(c.isdigit() for c in t):
        return None
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in t:
        partes = t.split(",")
        t = t.replace(",", ".") if len(partes) == 2 and len(partes[1]) != 3 else t.replace(",", "")
    elif t.count(".") == 1 and len(t.split(".")[1]) == 3 and len(t.split(".")[0]) <= 3 and t.split(".")[0] != "0":
        t = t.replace(".", "")  # 4.762 -> milhar (pt-BR)
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def numeros(texto):
    out = []
    for m in RE_NUMERO.finditer(texto):
        v = para_numero(m.group(0))
        if v is not None:
            out.append(v)
    return out


def reais(texto):
    return [v for v in (para_numero(m.group(1)) for m in RE_REAIS.finditer(texto)) if v is not None]


def parece_recurso(nome):
    return nome in ("ec2", "s3") or nome.startswith("stg") or nome.split("-")[0] in PREFIXOS


# ------------------------------------------------------------------ o que as ferramentas mostram
def saida_das_ferramentas():
    """Tudo o que os agentes conseguem ver pelas ferramentas (o 'universo' permitido de nomes e valores)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    def roda(args, extra=None):
        r = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env={**env, **(extra or {})})
        return r.stdout

    partes = [roda(["tools/cost_query.py", "resumo"]), roda(["tools/cost_query.py", "anomalias"]),
              roda(["tools/doc_logicapp.py", "listar"]), roda(["tools/doc_logicapp.py", "achados"])]
    nomes_csv = set(re.findall(r"Disponíveis: (.*)", roda(["tools/cost_query.py", "recurso"], {"nome": "?"})) or [""])
    for linha in nomes_csv:
        for n in [x.strip() for x in linha.split(",") if x.strip()]:
            partes.append(roda(["tools/cost_query.py", "recurso"], {"nome": n}))
    for n in re.findall(r"^- ([\w-]+):", partes[2], re.M):
        partes.append(roda(["tools/doc_logicapp.py", "resumo"], {"nome": n}))
    for arq in sorted((ROOT / "logicapps" / "versoes").glob("*.json")):  # comparações de versões que o agente pode pedir
        partes.append(roda(["tools/comparar_logicapp.py", "anterior", arq.name.split(".")[0], "--saida",
                            str(Path(tempfile.gettempdir()) / "avaliar-comparacao.md")]))
    partes.append(roda(["tools/finops_tenants.py", "tenants"]))  # visão por cliente (tenant)
    for t in json.loads((ROOT / "data" / "tenants" / "tenants.json").read_text(encoding="utf-8")):
        partes.append(roda(["tools/finops_tenants.py", "tenant"], {"tenant": t["nome"]}))
        partes.append(roda(["tools/finops_tenants.py", "economia"], {"tenant": t["nome"]}))
    rel = ROOT / "relatorios" / "relatorio-finops.md"
    if rel.exists():
        partes.append(rel.read_text(encoding="utf-8"))
    return "\n".join(partes)


class Universo:
    def __init__(self, texto):
        self.nomes = {n for n in RE_NOME.findall(texto.lower())}
        self.valores = reais(texto) + numeros(texto)

    def valor_conhecido(self, v):
        return any(abs(v - x) <= TOLERANCIA for x in self.valores)


# ------------------------------------------------------------------ correção
def exigencia_ok(exig, resposta_norm, nums):
    if isinstance(exig, (int, float)):
        return any(abs(exig - n) <= TOLERANCIA for n in nums)
    if isinstance(exig, dict) and "qualquer" in exig:
        return any(exigencia_ok(e, resposta_norm, nums) for e in exig["qualquer"])
    return sem_acento(str(exig)) in resposta_norm


def descreve(exig):
    if isinstance(exig, dict):
        return " ou ".join(descreve(e) for e in exig["qualquer"])
    if isinstance(exig, float):
        return f"{exig:.2f}".replace(".", ",")
    return str(exig)


def corrigir(caso, resposta, universo):
    norm = sem_acento(resposta)
    nums = numeros(resposta)
    faltou = [descreve(e) for e in caso["deve_conter"] if not exigencia_ok(e, norm, nums)]
    total = len(caso["deve_conter"])
    pontos = (total - len(faltou)) / total if total else 1.0
    permitidos_pergunta = set(RE_NOME.findall(caso["pergunta"].lower()))
    inventados = []
    for n in sorted(set(RE_NOME.findall(resposta.lower()))):
        if parece_recurso(n) and n not in universo.nomes and n not in permitidos_pergunta:
            inventados.append(f"recurso '{n}'")
    for v in reais(resposta):
        if not universo.valor_conhecido(v):
            inventados.append(f"valor R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    for proibido in caso.get("nao_deve_conter", []):  # isolamento: dado de outro cliente na resposta
        if sem_acento(proibido) in norm:
            inventados.append(f"vazou '{proibido}' (de outro cliente)")
    if not resposta.strip():
        situacao = "sem resposta"
    elif pontos == 1 and not inventados:
        situacao = "acertou"
    elif pontos == 0:
        situacao = "errou"
    else:
        situacao = "parcial"
    return {"id": caso["id"], "equipe": caso["equipe"], "pergunta": caso["pergunta"], "situacao": situacao,
            "pontos": round(pontos, 3), "faltou": faltou, "inventou": inventados,
            "ferramenta_em_texto": chamada_em_texto(resposta)}


# ------------------------------------------------------------------ rodar os agentes
def yaml_com_permissoes(equipe, pasta, modelo_dmr=None, contexto=None):
    """Cópia do YAML da equipe com uma lista 'permissions.allow' (doc oficial: configuration/permissions):
    com --safety restricted, só essas ferramentas rodam sem perguntar.
    Para outro modelo local (dmr), troca só o nome do modelo no YAML: assim ficam as mesmas opções
    (tamanho de contexto, max_tokens) e a comparação é justa. O original em agents/ não é alterado."""
    original = EQUIPES[equipe].read_text(encoding="utf-8")
    if modelo_dmr:
        original, n = re.subn(r"(?m)^(\s+provider: dmr\n\s+model: ).*$", lambda m: m.group(1) + modelo_dmr, original)
        if n != 1:
            raise SystemExit(f"RESULTADO: ERRO — não achei o modelo dmr em {EQUIPES[equipe].name}")
    if contexto:
        original = re.sub(r"(?m)^(\s+context_size: )\d+", lambda m: m.group(1) + str(contexto), original)
    bloco = "\npermissions:\n  allow:\n" + "".join(f'    - "{t}"\n' for t in PERMITIDAS[equipe])
    destino = Path(pasta) / f"{equipe}.yaml"
    destino.write_text(original.rstrip() + "\n" + bloco, encoding="utf-8")
    return destino


def perguntar(cfg, pergunta, modelo, limite_s):
    cmd = ["docker", "agent", "run", "--exec", "--last", "--safety", os.environ.get("AVALIAR_SEGURANCA", "restricted")]
    if modelo and not modelo.startswith("dmr/"):  # modelo de outro provedor: --model (doc: CLI reference)
        cmd += ["--model", modelo]
    cmd += [str(cfg), pergunta]
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                         env={**os.environ, "PYTHONIOENCODING": "utf-8", "TELEMETRY_ENABLED": "false"},
                         start_new_session=os.name != "nt")
    try:
        out, err = p.communicate(timeout=limite_s)
        return out.strip(), err.strip(), p.returncode, time.time() - t0
    except subprocess.TimeoutExpired:
        mata_arvore(p)
        return "", f"passou de {limite_s} s", -1, time.time() - t0


def mata_arvore(p):
    """No tempo limite, encerra o docker E os processos filhos dele (o plugin docker-agent).
    Só matar o 'docker' deixa o filho segurando a saída e o Python fica esperando para sempre (acontece no Windows)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def baixa_modelo(modelo):
    """Baixa o modelo antes de começar (docker model pull), com o progresso na tela.
    Assim o download não conta no tempo de nenhuma resposta. Se já estiver baixado, é rápido."""
    print(f"Conferindo o modelo {modelo} (docker model pull; na primeira vez baixa alguns GB)...", flush=True)
    r = subprocess.run(["docker", "model", "pull", modelo])
    return r.returncode == 0


def confere_docker_agent():
    if not shutil.which("docker"):
        return "não achei o comando 'docker' (abra o Docker Desktop)"
    r = subprocess.run(["docker", "agent", "run", "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return "o 'docker agent' não respondeu (Docker Desktop 4.63+ já traz o Docker Agent)"
    falta = [f for f in ("--exec", "--last", "--safety", "--model") if f not in r.stdout]
    if falta:
        return f"esta versão do Docker Agent não tem {', '.join(falta)}: atualize o Docker Desktop"
    return None


# ------------------------------------------------------------------ relatório
def resumo(resultados):
    n = len(resultados)
    if not n:
        return {"perguntas": 0}
    return {"perguntas": n,
            "acertos": sum(r["situacao"] == "acertou" for r in resultados),
            "pontos_pct": round(100 * sum(r["pontos"] for r in resultados) / n, 1),
            "com_invencao": sum(bool(r["inventou"]) for r in resultados),
            "invencao_pct": round(100 * sum(bool(r["inventou"]) for r in resultados) / n, 1),
            "ferramenta_em_texto": sum(chamada_em_texto(r.get("resposta", "")) for r in resultados),
            "tempo_medio_s": round(sum(r.get("tempo_s", 0) for r in resultados) / n, 1)}


def grava(rodada):
    SAIDA.mkdir(parents=True, exist_ok=True)
    nome = f"{rodada['quando'][:16].replace(':', '').replace('T', '-')}-{re.sub(r'[^a-z0-9]+', '-', rodada['modelo'].lower()).strip('-')}"
    (SAIDA / f"{nome}.json").write_text(json.dumps(rodada, ensure_ascii=False, indent=2), encoding="utf-8")
    r = rodada["resumo"]
    L = [f"# Avaliação dos agentes — {rodada['modelo']}", "",
         f"Rodada de {rodada['quando']} · {r['perguntas']} respostas · perguntas em `evals/casos.json`.", "",
         f"- **Acertos completos:** {r['acertos']} de {r['perguntas']} · **pontuação:** {r['pontos_pct']}%",
         f"- **Respostas com algo inventado:** {r['com_invencao']} de {r['perguntas']} ({r['invencao_pct']}%)",
         f"- **Tempo médio por resposta:** {r['tempo_medio_s']} s", "",
         "| Pergunta | Situação | Faltou | Inventou | Tempo |", "|---|---|---|---|---|"]
    for x in rodada["resultados"]:
        L.append(f"| `{x['id']}` | {x['situacao']} | {'; '.join(x['faltou']) or '–'} | {'; '.join(x['inventou']) or '–'} "
                 f"| {x.get('tempo_s', 0):.0f} s |")
    L += ["", "## Respostas", ""]
    for x in rodada["resultados"]:
        texto = (x.get("resposta") or "(vazia)").replace("\n", "\n> ")
        L += [f"### {x['id']} — {x['situacao']}", f"**Pergunta:** {x['pergunta']}", "", f"> {texto}", ""]
    (SAIDA / f"{nome}.md").write_text("\n".join(L), encoding="utf-8")
    atualiza_resumo()
    return SAIDA / f"{nome}.md"


def atualiza_resumo():
    linhas = []
    for p in sorted(SAIDA.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        r = d["resumo"]
        texto_ = sum(chamada_em_texto(x.get("resposta", "")) for x in d["resultados"])  # recalcula: vale para rodadas antigas
        linhas.append(f"| {d['quando'][:16].replace('T', ' ')} | `{d['modelo']}` | {r['acertos']}/{r['perguntas']} | {r['pontos_pct']}% "
                      f"| {r['invencao_pct']}% | {texto_}/{r['perguntas']} | {r['tempo_medio_s']} s | [{p.stem}]({p.stem}.md) |")
    texto = ["# Comparação das rodadas", "",
             "Pontuação = parte do que cada resposta precisava trazer. Invenção = respostas que citaram recurso ou valor em R$ "
             "que não saiu das ferramentas. Ferramenta em texto = respostas em que o modelo escreveu a chamada da ferramenta "
             "(ex.: `transfer_task(...)`) em vez de chamá-la: sinal de modelo sem suporte a ferramentas.", "",
             "| Quando | Modelo | Acertos | Pontuação | Invenção | Ferramenta em texto | Tempo médio | Detalhes |",
             "|---|---|---|---|---|---|---|---|",
             *linhas]
    (SAIDA / "RESUMO.md").write_text("\n".join(texto) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ principal
def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modelo", help="modelo no formato do --model do Docker Agent, ex.: dmr/ai/gemma3 (padrão: o do YAML)")
    ap.add_argument("--so", choices=sorted(EQUIPES), help="só uma equipe")
    ap.add_argument("--caso", help="só um caso (id)")
    ap.add_argument("--repetir", type=int, default=1, help="quantas vezes cada pergunta (modelos variam entre rodadas)")
    ap.add_argument("--limite", type=int, default=600, help="segundos máximos por resposta")
    ap.add_argument("--contexto", type=int, help="tamanho de contexto do modelo local (padrão: o do YAML, 16384)")
    ap.add_argument("--corrigir", help="arquivo JSON {id: resposta} ou [{id, resposta}] para corrigir sem rodar modelo")
    a = ap.parse_args(argv)

    casos = json.loads(CASOS.read_text(encoding="utf-8"))["casos"]
    casos = [c for c in casos if (not a.so or c["equipe"] == a.so) and (not a.caso or c["id"] == a.caso)]
    universo = Universo(saida_das_ferramentas())
    resultados = []

    if a.corrigir:
        dados = json.loads(Path(a.corrigir).read_text(encoding="utf-8"))
        if isinstance(dados, dict) and "resultados" in dados:  # um arquivo de evals/resultados: corrige de novo
            dados = dados["resultados"]
        respostas = dados if isinstance(dados, dict) else {d["id"]: d["resposta"] for d in dados}
        for c in casos:
            if c["id"] in respostas:
                r = corrigir(c, respostas[c["id"]], universo)
                r["resposta"] = respostas[c["id"]]
                resultados.append(r)
                print(f"  {r['situacao']:<12} {c['id']}" + (f"  inventou: {', '.join(r['inventou'])}" if r["inventou"] else ""))
        print(json.dumps(resumo(resultados), ensure_ascii=False))
        print("RESULTADO: AVALIAÇÃO CONCLUÍDA")
        return 0

    problema = confere_docker_agent()
    if problema:
        print(f"RESULTADO: ERRO — {problema}")
        return 1
    dmr_modelo = a.modelo[len("dmr/"):] if a.modelo and a.modelo.startswith("dmr/") else (None if a.modelo else "ai/qwen3")
    if dmr_modelo and not baixa_modelo(dmr_modelo):
        print(f"RESULTADO: ERRO — não consegui baixar {dmr_modelo} (o Docker Model Runner está ativado?)")
        return 1
    modelo = a.modelo or "padrão do YAML (dmr/ai/qwen3)"
    print(f"Avaliando {len(casos)} pergunta(s) × {a.repetir} com {modelo}. Cada resposta pode levar alguns minutos no modelo local.\n")
    with tempfile.TemporaryDirectory() as tmp:
        dmr = a.modelo[len("dmr/"):] if a.modelo and a.modelo.startswith("dmr/") else None
        cfgs = {e: yaml_com_permissoes(e, tmp, dmr, a.contexto) for e in EQUIPES}
        for i, c in enumerate(casos * a.repetir, 1):
            resposta, erro, codigo, dur = perguntar(cfgs[c["equipe"]], c["pergunta"], a.modelo, a.limite)
            r = corrigir(c, resposta, universo)
            r.update({"resposta": resposta, "tempo_s": round(dur, 1), "codigo_saida": codigo})
            if codigo != 0 and erro:
                r["erro"] = erro[-800:]
            resultados.append(r)
            extra = f"  inventou: {', '.join(r['inventou'])}" if r["inventou"] else ""
            extra += f"  faltou: {', '.join(r['faltou'])}" if r["faltou"] else ""
            extra += "  [escreveu a chamada da ferramenta como texto, não chamou]" if r["ferramenta_em_texto"] else ""
            print(f"[{i}/{len(casos) * a.repetir}] {r['situacao']:<12} {c['id']} ({dur:.0f} s){extra}", flush=True)
            if codigo != 0 and erro:
                print(f"      erro do docker agent: {erro.splitlines()[-1][:200]}")

    rodada = {"quando": datetime.now().isoformat(timespec="seconds"), "modelo": a.modelo or "dmr/ai/qwen3 (YAML)",
              "resumo": resumo(resultados), "resultados": resultados}
    arq = grava(rodada)
    r = rodada["resumo"]
    if r["ferramenta_em_texto"]:
        print(f"\nAtenção: em {r['ferramenta_em_texto']} resposta(s) o modelo escreveu a chamada da ferramenta como texto em vez de "
              "chamá-la. Esse modelo provavelmente não tem suporte a chamada de ferramentas no Docker Model Runner.")
    print(f"\nAcertos: {r['acertos']}/{r['perguntas']} · pontuação {r['pontos_pct']}% · com invenção {r['invencao_pct']}% "
          f"· {r['tempo_medio_s']} s por resposta")
    print(f"Detalhes: {arq.relative_to(ROOT)}  ·  comparação: evals/resultados/RESUMO.md")
    print("RESULTADO: AVALIAÇÃO CONCLUÍDA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
