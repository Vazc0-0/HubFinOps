"""Leva para o Postgres do Grafana os dados reais do Azure, o histórico do piloto e os chamados.

Fontes (arquivos que os outros scripts já geram):
  relatorios/azure/<logic-app>-execucoes.json  -> tabela azure_execucoes
  relatorios/azure/<logic-app>-metricas.json   -> tabela azure_metricas (série diária do Azure Monitor)
  relatorios/azure/precos_logicapps.json       -> tabela azure_precos
  logicapps/reais/<logic-app>.json             -> tabela azure_previsto (estimativa do leitor x medido)
  relatorios/historico.jsonl                   -> tabela historico
  chamados/*.json                              -> tabela chamados

Cada carga apaga e recria o conteúdo dessas tabelas (pode rodar quantas vezes quiser).
Usa o psql de dentro do container (docker compose exec), então não precisa instalar nada no Windows.

Uso:
  python tools/carregar_grafana.py
  python tools/carregar_grafana.py --simular-falha     (acrescenta UMA execução com falha marcada como
                                                        SIMULADA, para ver o alerta e o chamado funcionando)
  python tools/carregar_grafana.py --limpar-simulacao  (tira as execuções simuladas; o alerta volta ao normal)
"""
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import historico  # noqa: E402
import logicapp_parser as lp  # noqa: E402

ROOT = historico.ROOT
AZ = ROOT / "relatorios" / "azure"
CHAMADOS = ROOT / "chamados"

DDL = """
CREATE TABLE IF NOT EXISTS azure_execucoes (logic_app text, execucao text PRIMARY KEY, status text,
  inicio timestamptz, fim timestamptz, acoes_total int, acoes_rodaram int, acoes_puladas int,
  acoes_com_falha text, simulada boolean DEFAULT false);
CREATE TABLE IF NOT EXISTS azure_metricas (logic_app text, metrica text, momento timestamptz, total numeric,
  PRIMARY KEY (logic_app, metrica, momento));
CREATE TABLE IF NOT EXISTS azure_precos (medidor text, a_partir_de numeric, preco numeric, unidade text,
  regiao text, moeda text, consultado_em timestamptz);
CREATE TABLE IF NOT EXISTS azure_previsto (logic_app text PRIMARY KEY, previsto_por_execucao numeric,
  fixas int, por_item int, itens_no_loop int, medido_acoes numeric, medido_disparos numeric,
  medido_por_execucao numeric, execucoes_mes numeric, custo_mes_brl numeric);
CREATE TABLE IF NOT EXISTS historico (id text PRIMARY KEY, tarefa text, origem text, status text,
  inicio timestamptz, fim timestamptz, duracao_s numeric, resumo text);
CREATE TABLE IF NOT EXISTS chamados (id text PRIMARY KEY, criado_em timestamptz, titulo text, prioridade text,
  regra text, alvo text, status text, resolvido_em timestamptz);
"""


def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def insert(tabela, linhas):
    if not linhas:
        return ""
    cols = list(linhas[0])
    vals = ",\n".join("(" + ", ".join(q(l[c]) for c in cols) + ")" for l in linhas)
    return f"INSERT INTO {tabela} ({', '.join(cols)}) VALUES\n{vals};\n"


SIMULACAO = AZ / "simulacao_falha.json"


def previsto_x_medido(la, dados=None):
    """Estimativa do leitor (ações por execução) x o que o Azure Monitor mediu (mesma conta do 'conferir')."""
    real = ROOT / "logicapps" / "reais" / f"{la}.json"
    met = AZ / f"{la}-metricas.json"
    if not real.exists():
        return None
    if dados is None:
        dados = json.loads(met.read_text(encoding="utf-8")) if met.exists() else {}
    info = lp.ler(json.loads(real.read_text(encoding="utf-8-sig")))
    cob = info["cobranca"]
    precos = json.loads((AZ / "precos_logicapps.json").read_text(encoding="utf-8")) \
        if (AZ / "precos_logicapps.json").exists() else {}
    itens = len(precos.get("precos", [])) if precos else None
    por_item = sum(cob["por_item_de_loop"].values())
    previsto = cob["fixas_por_execucao"] + por_item * (itens or 0)
    tot = dados.get("totais", {})
    disp = tot.get("BillableTriggerExecutions") or 0
    execs_mes = float(cob.get("execucoes_por_mes") or 0)
    # custo do mês: ações nativas além da faixa grátis × preço (tabela oficial trazida pela própria Logic App)
    nat = [(float(p["a_partir_de"]), float(p["preco"])) for p in precos.get("precos", [])
           if p["medidor"] == "Consumption Built-in Actions"]
    gratis = max((a for a, _ in nat), default=0)
    preco_nat = max(nat)[1] if nat else 0
    custo = max(0.0, execs_mes * (previsto + 1) - gratis) * preco_nat
    return {"logic_app": la, "previsto_por_execucao": previsto, "fixas": cob["fixas_por_execucao"],
            "por_item": por_item, "itens_no_loop": itens,
            "medido_acoes": tot.get("BillableActionExecutions"), "medido_disparos": disp,
            "medido_por_execucao": (tot.get("BillableActionExecutions") or 0) / disp if disp else None,
            "execucoes_mes": round(execs_mes, 2), "custo_mes_brl": round(custo, 4)}


def montar_sql(simular_falha=False, limpar_simulacao=False):
    sql = [DDL, "BEGIN;", "TRUNCATE azure_execucoes, azure_metricas, azure_precos, azure_previsto, historico, chamados;"]
    resumo = {}

    execs = []
    for arq in sorted(AZ.glob("*-execucoes.json")):
        la = arq.name[:-len("-execucoes.json")]
        for e in json.loads(arq.read_text(encoding="utf-8")):
            st = e["acoes"].values()
            execs.append({"logic_app": la, "execucao": e["execucao"], "status": e["status"], "inicio": e["inicio"],
                          "fim": e["fim"], "acoes_total": len(e["acoes"]),
                          "acoes_rodaram": sum(1 for s in st if s != "Skipped"),
                          "acoes_puladas": sum(1 for s in st if s == "Skipped"),
                          "acoes_com_falha": ", ".join(n for n, s in e["acoes"].items() if s == "Failed") or None,
                          "simulada": False})
    if simular_falha:
        la = execs[0]["logic_app"] if execs else "la-precos-logicapps"
        agora = historico.agora()
        acoes = {"Inicializar_linhas": "Succeeded", "Tentar": "Failed", "Consultar_precos": "Failed",
                 "Registrar_falha": "Succeeded", "Encerrar_com_falha": "Succeeded"}
        sim = json.loads(SIMULACAO.read_text(encoding="utf-8")) if SIMULACAO.exists() else []
        sim.append({"logic_app": la, "execucao": "SIMULADA-" + datetime.now().strftime("%Y%m%d%H%M%S"),
                    "status": "Failed", "inicio": agora, "fim": agora, "acoes": acoes})
        AZ.mkdir(parents=True, exist_ok=True)
        SIMULACAO.write_text(json.dumps(sim, ensure_ascii=False, indent=2), encoding="utf-8")
    if limpar_simulacao and SIMULACAO.exists():
        SIMULACAO.write_text("[]", encoding="utf-8")
    for e in (json.loads(SIMULACAO.read_text(encoding="utf-8")) if SIMULACAO.exists() else []):
        st = e["acoes"].values()
        execs.append({"logic_app": e["logic_app"], "execucao": e["execucao"], "status": e["status"],
                      "inicio": e["inicio"], "fim": e["fim"], "acoes_total": len(e["acoes"]),
                      "acoes_rodaram": sum(1 for x in st if x != "Skipped"),
                      "acoes_puladas": sum(1 for x in st if x == "Skipped"),
                      "acoes_com_falha": ", ".join(n for n, x in e["acoes"].items() if x == "Failed"),
                      "simulada": True})
    sql.append(insert("azure_execucoes", execs))
    resumo["execuções do Azure"] = len(execs)

    mets, previstos = [], []
    for arq in sorted(AZ.glob("*-metricas.json")):
        la = arq.name[:-len("-metricas.json")]
        dados = json.loads(arq.read_text(encoding="utf-8"))
        for serie in (dados.get("bruto") or {}).get("value", []):
            for ts in serie.get("timeseries", []):
                for d in ts.get("data", []):
                    mets.append({"logic_app": la, "metrica": serie["name"]["value"], "momento": d["timeStamp"],
                                 "total": d.get("total") or 0})
        p = previsto_x_medido(la, dados)
        if p:
            previstos.append(p)
    sql.append(insert("azure_metricas", mets))
    sql.append(insert("azure_previsto", previstos))
    resumo["pontos de métrica"] = len(mets)

    precos = json.loads((AZ / "precos_logicapps.json").read_text(encoding="utf-8")) \
        if (AZ / "precos_logicapps.json").exists() else {}
    sql.append(insert("azure_precos", [{"medidor": p["medidor"], "a_partir_de": float(p["a_partir_de"]),
                                        "preco": float(p["preco"]), "unidade": p["unidade"],
                                        "regiao": precos.get("regiao"), "moeda": precos.get("moeda"),
                                        "consultado_em": precos.get("consultado_em")}
                                       for p in precos.get("precos", [])]))
    resumo["preços"] = len(precos.get("precos", []))

    hist = [{"id": e["id"], "tarefa": e.get("tarefa"), "origem": e.get("origem"), "status": e.get("status"),
             "inicio": e.get("inicio"), "fim": e.get("fim"), "duracao_s": e.get("duracao_s"),
             "resumo": (e.get("resumo") or "")[:300]} for e in historico.ler()]
    sql.append(insert("historico", hist))
    resumo["execuções no histórico"] = len(hist)

    ch = []
    for arq in sorted(CHAMADOS.glob("CH-*.json")):
        c = json.loads(arq.read_text(encoding="utf-8"))
        ch.append({"id": c["id"], "criado_em": c["criado_em"], "titulo": c["titulo"], "prioridade": c["prioridade"],
                   "regra": c["regra"], "alvo": c["alvo"], "status": c["status"], "resolvido_em": c.get("resolvido_em")})
    sql.append(insert("chamados", ch))
    resumo["chamados"] = len(ch)

    sql += ["GRANT SELECT ON azure_execucoes, azure_metricas, azure_precos, azure_previsto, historico, chamados "
            "TO grafana_reader;", "COMMIT;"]
    return "\n".join(s for s in sql if s), resumo


def psql_cmd():
    """Por padrão usa o psql do container; PILOTO_PSQL troca o comando (usado nos testes)."""
    if os.environ.get("PILOTO_PSQL"):
        return shlex.split(os.environ["PILOTO_PSQL"])
    return ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "finops_admin", "-d", "finops"]


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sql, resumo = montar_sql("--simular-falha" in argv, "--limpar-simulacao" in argv)
    r = subprocess.run(psql_cmd() + ["-v", "ON_ERROR_STOP=1", "-q"], input=sql.encode("utf-8"),
                       capture_output=True, cwd=ROOT)
    erro = r.stderr.decode("utf-8", errors="replace").strip()
    if r.returncode != 0:
        print(erro or r.stdout.decode("utf-8", errors="replace"))
        if "docker" in " ".join(psql_cmd()) and ("no such service" in erro or "not running" in erro
                                                 or "Cannot connect" in erro or "error during connect" in erro):
            print("Dica: suba o ambiente antes com: docker compose up -d")
        print("RESULTADO: ERRO ao carregar no Postgres")
        return 1
    for k, v in resumo.items():
        print(f"  {k}: {v}")
    print("RESULTADO: DADOS CARREGADOS NO GRAFANA")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
