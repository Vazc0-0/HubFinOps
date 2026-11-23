"""Receptor de alertas do Grafana: cada alerta disparado vira um CHAMADO com diagnóstico pronto.

O Grafana manda o alerta por webhook (contact point do tipo webhook, provisionado em
grafana/provisioning/alerting/). Este receptor:
  1. lê o alerta (formato JSON do webhook do Grafana: lista "alerts" com labels, annotations, values...);
  2. evita chamado repetido (o mesmo alerta, identificado pelo fingerprint, só abre um chamado);
  3. monta o DIAGNÓSTICO em código, a partir dos mesmos dados e ferramentas do piloto (nada vem de IA);
  4. grava chamados/CH-AAAAMMDD-NNN.json e .md (no formato de um ticket do Jira: resumo, prioridade,
     descrição, diagnóstico, próximos passos) e registra no histórico do hub;
  5. quando o Grafana avisa que o alerta foi resolvido, marca o chamado como Resolvido.

É uma simulação do Jira: o chamado fica em arquivo. Ligar a um Jira de verdade é trocar a etapa 4
por uma chamada à API do Jira (fica para quando houver acesso).

Uso:  python tools/receptor_chamados.py [--porta 8088]      (no docker compose ele sobe sozinho)
"""
import json
import os
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import historico  # noqa: E402

ROOT = historico.ROOT
PASTA = Path(os.environ.get("PILOTO_CHAMADOS_DIR", ROOT / "chamados"))
TRAVA = threading.Lock()
PRIORIDADE_ORDEM = {"Alta": 0, "Média": 1, "Baixa": 2}


def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ----------------------------------------------------------------- diagnósticos (código, não IA)
def diag_recurso_sem_dono(alvo, alerta):
    import cost_query as cq
    series, meta = cq.load()
    if alvo not in series:
        return "Média", [f"O recurso `{alvo}` não está nos dados de custo."], ["Conferir o nome do recurso."]
    s, m = series[alvo], meta[alvo]
    dias = sorted(s)
    achados = [a for a in cq._estende_picos(series, cq.detectar(series, meta)) if a["recurso"] == alvo]
    extra = sum(cq.custo_extra(series, a) for a in achados)
    com_custo = [d for d in dias if s[d] > 0]
    total = sum(s.values())
    ult30 = sum(s[d] for d in dias if d > dias[-1] - __import__("datetime").timedelta(days=30))
    linhas = [f"Recurso `{alvo}` ({m['servico']}, grupo `{m['rg']}`) **sem a tag `owner`**: ninguém responde por ele.",
              f"Tem custo desde {com_custo[0].strftime('%d/%m/%Y')}; custo diário foi de {brl(s[com_custo[0]])} "
              f"para {brl(s[dias[-1]])} em {dias[-1].strftime('%d/%m/%Y')}.",
              f"Custo no período dos dados: {brl(total)}; últimos 30 dias: {brl(ult30)}.",
              f"Custo extra atribuído pela detecção de anomalias: {brl(extra)} (prioridade {cq.prioridade(extra)})."]
    passos = ["Descobrir quem criou o recurso (Log de atividades do grupo de recursos no portal).",
              "Aplicar a tag `owner` com o responsável.",
              "Se não estiver em uso, exportar o que for preciso e excluir o recurso.",
              "Evitar novos casos: política do Azure que exige a tag `owner` na criação."]
    return cq.prioridade(extra), linhas, passos


def _execucoes(la):
    arq = ROOT / "relatorios" / "azure" / f"{la}-execucoes.json"
    reais = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else []
    sim = ROOT / "relatorios" / "azure" / "simulacao_falha.json"
    simuladas = [e for e in (json.loads(sim.read_text(encoding="utf-8")) if sim.exists() else []) if e["logic_app"] == la]
    return reais, simuladas


def diag_logicapp_falha(alvo, alerta):
    import doc_logicapp as dl
    import logicapp_parser as lp
    reais, simuladas = _execucoes(alvo)
    falhas = [dict(e, simulada=False) for e in reais if e["status"] == "Failed"] + [dict(e, simulada=True) for e in simuladas]
    real = ROOT / "logicapps" / "reais" / f"{alvo}.json"
    info = lp.ler(json.loads(real.read_text(encoding="utf-8-sig"))) if real.exists() else None
    linhas, passos = [], []
    if not falhas:
        linhas.append(f"O alerta indica falha na Logic App `{alvo}`, mas a última sincronização não trouxe a execução "
                      "com falha. Rode a sincronização com o Azure para atualizar.")
    for e in falhas[:3]:
        rot = " (SIMULADA para teste)" if e["simulada"] else ""
        acoes = [n for n, s in e["acoes"].items() if s == "Failed"]
        linhas.append(f"Execução `{e['execucao']}`{rot} de {e['inicio'][:19].replace('T', ' ')} terminou com "
                      f"**falha**; ações que falharam: {', '.join(f'`{a}`' for a in acoes) or 'não informado'}.")
        if info:
            por = {x["nome"]: x for x in info["acoes"]}
            for a in acoes:
                if a in por and por[a]["tipo"] not in lp.CONTAINERS:
                    x = por[a]
                    linhas.append(f"O que `{a}` faz (passo {x['numero']} da documentação): {dl.o_que_faz(x)}")
                    rt = x["retentativa"]
                    if rt["tipo"] != "none":
                        linhas.append(f"`{a}` já tem retentativa ({rt['tipo']}"
                                      + (f", {rt['tentativas']} tentativas" if rt["tentativas"] else "")
                                      + "): a falha persistiu depois das novas tentativas.")
    if info:
        trat = [x["nome"] for x in info["acoes"] if any(set(s) & {"Failed", "TimedOut"} for s in x["run_after"].values())]
        verbo = "roda" if len(trat) == 1 else "rodam"
        linhas.append("Tratamento de erro do fluxo: " + (", ".join(f"`{t}`" for t in trat) + f" {verbo} quando há falha."
                                                      if trat else "nenhum (a falha passa em silêncio)."))
    passos += ["Abrir a execução no portal (Logic App → Histórico de execuções) e ver a entrada e a saída da ação que falhou.",
               "Se for indisponibilidade do serviço externo, executar de novo mais tarde (Reenviar).",
               "Se repetir, revisar a configuração da ação conforme a documentação gerada (docs/logicapps).",
               "Depois de corrigir, sincronizar com o Azure para o alerta voltar ao normal."]
    return "Alta", linhas, passos


def diag_custo_divergente(alvo, alerta):
    import carregar_grafana as cg
    p = cg.previsto_x_medido(alvo)
    if not p:
        return "Média", [f"Sem dados de previsão para `{alvo}`."], ["Sincronizar com o Azure."]
    linhas = [f"O leitor previu **{p['previsto_por_execucao']:g} ações cobradas por execução** "
              f"({p['fixas']} fixas + {p['por_item']} por item × {p['itens_no_loop']} itens).",
              f"O Azure Monitor mediu {p['medido_acoes']:g} ações em {p['medido_disparos']:g} disparos = "
              f"**{p['medido_por_execucao']:g} por execução**."]
    passos = ["Ver se houve execução com falha ou cancelada (contam ações diferentes).",
              "Ver se o loop processou um número diferente de itens nessa execução.",
              "Se a diferença for estrutural, abrir caso de ajuste no leitor (tools/logicapp_parser.py) com o JSON."]
    return "Média", linhas, passos


REGRAS = {"recurso_sem_dono": ("Recurso sem dono gerando custo", diag_recurso_sem_dono),
          "logicapp_falha": ("Logic App com execução que falhou", diag_logicapp_falha),
          "custo_divergente": ("Custo medido diferente do previsto", diag_custo_divergente)}


# ----------------------------------------------------------------- chamados
def _estado():
    arq = PASTA / "_estado.json"
    return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}


def _salva_estado(e):
    (PASTA / "_estado.json").write_text(json.dumps(e, ensure_ascii=False, indent=2), encoding="utf-8")


def _novo_id():
    hoje = datetime.now().strftime("%Y%m%d")
    n = len(list(PASTA.glob(f"CH-{hoje}-*.json"))) + 1
    return f"CH-{hoje}-{n:03d}"


def _markdown(c):
    L = [f"# {c['id']} — {c['titulo']}", "",
         "| Campo | Valor |", "|---|---|",
         f"| Status | {c['status']} |", f"| Prioridade | {c['prioridade']} |",
         f"| Componente | {c['componente']} |", f"| Alvo | `{c['alvo']}` |",
         f"| Aberto em | {c['criado_em'][:19].replace('T', ' ')} |",
         f"| Origem | {c['origem']} |"]
    if c.get("resolvido_em"):
        L.append(f"| Resolvido em | {c['resolvido_em'][:19].replace('T', ' ')} |")
    L += ["", "## Descrição", c["descricao"], "", "## Diagnóstico (gerado por código)"]
    L += [f"- {l}" for l in c["diagnostico"]]
    L += ["", "## Próximos passos"] + [f"{k}. {p}" for k, p in enumerate(c["proximos_passos"], 1)]
    if c.get("link_grafana"):
        L += ["", f"[Abrir a regra de alerta no Grafana]({c['link_grafana']})"]
    L += ["", "> Chamado simulado (formato Jira) criado pelo receptor de alertas do Piloto Agentes de IA."]
    return "\n".join(L) + "\n"


def _grava(c):
    PASTA.mkdir(parents=True, exist_ok=True)
    (PASTA / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    (PASTA / f"{c['id']}.md").write_text(_markdown(c), encoding="utf-8")


def processar(payload):
    """Processa um webhook do Grafana. Devolve [(ação, id_do_chamado), ...]."""
    resultado = []
    with TRAVA:
        PASTA.mkdir(parents=True, exist_ok=True)
        estado = _estado()
        for al in payload.get("alerts", []):
            lab, ann = al.get("labels", {}), al.get("annotations", {})
            regra = lab.get("regra")
            if regra not in REGRAS:
                resultado.append(("ignorado", None))
                continue
            alvo = lab.get("recurso") or lab.get("logic_app") or "?"
            chave = al.get("fingerprint") or f"{regra}:{alvo}"
            atual = estado.get(chave)
            if al.get("status") == "resolved":
                if atual:
                    c = json.loads((PASTA / f"{atual}.json").read_text(encoding="utf-8"))
                    if c["status"] != "Resolvido":
                        c["status"], c["resolvido_em"] = "Resolvido", historico.agora()
                        _grava(c)
                        historico.evento("Alerta resolvido → chamado fechado", "ok", f"{c['id']} {c['titulo']}",
                                         origem="Grafana (alerta)")
                    resultado.append(("resolvido", atual))
                    del estado[chave]
                else:
                    resultado.append(("ignorado", None))
                continue
            if atual:  # o Grafana reenvia alertas ativos de tempos em tempos: não duplica
                resultado.append(("já existe", atual))
                continue
            titulo_base, diag = REGRAS[regra]
            prioridade, linhas, passos = diag(alvo, al)
            c = {"id": _novo_id(), "criado_em": historico.agora(), "status": "Aberto",
                 "titulo": f"{titulo_base}: {alvo}", "prioridade": prioridade, "regra": regra, "alvo": alvo,
                 "componente": "FinOps" if regra == "recurso_sem_dono" else "Logic Apps",
                 "origem": f"Alerta do Grafana: {lab.get('alertname', '?')}",
                 "descricao": ann.get("description") or ann.get("summary") or titulo_base,
                 "valores": al.get("values") or {}, "fingerprint": chave,
                 "diagnostico": linhas, "proximos_passos": passos,
                 "link_grafana": al.get("generatorURL")}
            _grava(c)
            estado[chave] = c["id"]
            historico.evento("Alerta do Grafana → chamado", "ok", f"{c['id']} ({c['prioridade']}) {c['titulo']}",
                             origem="Grafana (alerta)")
            resultado.append(("criado", c["id"]))
        _salva_estado(estado)
    return resultado


def listar():
    out = []
    for arq in sorted(PASTA.glob("CH-*.json"), reverse=True):
        out.append(json.loads(arq.read_text(encoding="utf-8")))
    return out


# ----------------------------------------------------------------- servidor HTTP
class Receptor(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[receptor] {self.address_string()} {fmt % args}\n")

    def _json(self, codigo, corpo):
        b = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/chamados"):
            return self._json(200, listar())
        return self._json(200, {"status": "receptor de alertas no ar", "chamados": len(listar())})

    def do_POST(self):
        if not self.path.startswith("/alerta"):
            return self._json(404, {"erro": "use POST /alerta"})
        tam = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(tam).decode("utf-8"))
        except ValueError:
            return self._json(400, {"erro": "JSON inválido"})
        if os.environ.get("PILOTO_GUARDAR_PAYLOAD"):  # para capturar exemplos reais do Grafana nos testes
            Path(os.environ["PILOTO_GUARDAR_PAYLOAD"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                                                  encoding="utf-8")
        try:
            r = processar(payload)
        except Exception as e:  # noqa: BLE001
            historico.evento("Alerta do Grafana → chamado", "falhou", f"{type(e).__name__}: {e}", origem="Grafana (alerta)")
            return self._json(500, {"erro": str(e)})
        return self._json(200, {"resultado": r})


def servir(porta=8088, host="0.0.0.0"):
    srv = ThreadingHTTPServer((host, porta), Receptor)
    print(f"Receptor de alertas ouvindo em http://{host}:{porta}/alerta (chamados em {PASTA})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    porta = int(sys.argv[sys.argv.index("--porta") + 1]) if "--porta" in sys.argv else 8088
    servir(porta)
