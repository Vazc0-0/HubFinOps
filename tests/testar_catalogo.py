"""Confere o catálogo de automações (tools/catalogo_logicapps.py) sem Azure de verdade.

  1. Gabarito escrito à mão (logicapps/operacao/gabarito_catalogo.json): situação, dono, execuções, falhas,
     taxa, última execução, sinais, causa provável, conexões compartilhadas e quem chama quem.
  2. Casos sintéticos com resposta conhecida: parada, desabilitada, limite de 10% de falhas, falha pontual,
     sem dono, conexão desconhecida, sem dados de operação.
  3. Sincronização real simulada: `azure_logicapp.py operacao` contra um Azure falso (servidor local), e o
     catálogo lendo o arquivo gravado. Confere que nenhuma credencial da conexão vai para o arquivo.
  4. Página CATALOGO.md: só cita Logic Apps que existem e traz todas.
  5. Sabotagem: com um número trocado nos dados, a comparação com o gabarito tem de reprovar.

Uso:  python tests/testar_catalogo.py      Termina com "RESULTADO: CATÁLOGO CORRETO".
"""
import copy
import json
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import azure_logicapp as az  # noqa: E402
import catalogo_logicapps as cl  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ok, falhas = 0, []


def confere(cond, msg):
    global ok
    if cond:
        ok += 1
    else:
        falhas.append(msg)
    return cond


VAZIA = Path(tempfile.mkdtemp(prefix="catalogo-vazio-"))
cl.OPERACAO_REAL = VAZIA  # o gabarito é dos exemplos: ignora a Logic App real sincronizada nesta máquina
BASE = json.loads(cl.OPERACAO_EXEMPLOS.read_text(encoding="utf-8"))
GAB = json.loads((ROOT / "logicapps" / "operacao" / "gabarito_catalogo.json").read_text(encoding="utf-8"))


def com_dados(dados):
    """Monta o catálogo com outros dados de operação (arquivo temporário)."""
    p = Path(tempfile.mkdtemp(prefix="catalogo-")) / "op.json"
    p.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    antes, cl.OPERACAO_EXEMPLOS = cl.OPERACAO_EXEMPLOS, p
    try:
        return cl.montar()
    finally:
        cl.OPERACAO_EXEMPLOS = antes


def por_nome(cat):
    return {x["nome"]: x for x in cat["logicapps"]}


def diferencas(cat, gab):
    """Tudo o que difere do gabarito (lista vazia = bate)."""
    out = []
    itens = por_nome(cat)
    if cat["por_situacao"] != gab["por_situacao"]:
        out.append(f"contagem por situação {cat['por_situacao']} ≠ {gab['por_situacao']}")
    if set(itens) != set(gab["logicapps"]):
        out.append(f"Logic Apps {sorted(itens)} ≠ {sorted(gab['logicapps'])}")
    for n, g in gab["logicapps"].items():
        it = itens.get(n)
        if not it:
            continue
        if it["situacao"] != g["situacao"]:
            out.append(f"{n}: situação {it['situacao']} ≠ {g['situacao']}")
        if g["situacao"] == "Sem dados":
            if it["operacao"] is not None:
                out.append(f"{n}: devia estar sem dados de operação")
            continue
        o = it["operacao"] or {}
        for k in ("execucoes_30d", "falhas_30d", "taxa_falha_pct", "ultima_execucao", "ultimo_status"):
            if o.get(k) != g[k]:
                out.append(f"{n}: {k} {o.get(k)} ≠ {g[k]}")
        if it["dono"] != g["dono"]:
            out.append(f"{n}: dono {it['dono']} ≠ {g['dono']}")
        if sorted(s["sinal"] for s in it["sinais"]) != sorted(g["sinais"]):
            out.append(f"{n}: sinais {[s['sinal'] for s in it['sinais']]} ≠ {g['sinais']}")
        texto_sinais = " ".join(s["detalhe"] for s in it["sinais"])
        for t in g.get("causa_contem", []):
            if t not in texto_sinais:
                out.append(f"{n}: a causa provável devia citar '{t}' ({texto_sinais})")
        if "chama" in g and sorted({c["nome"] for c in it["chama"]}) != g["chama"]:
            out.append(f"{n}: chama {it['chama']} ≠ {g['chama']}")
        if "chamada_por" in g and it["chamada_por"] != g["chamada_por"]:
            out.append(f"{n}: chamada por {it['chamada_por']} ≠ {g['chamada_por']}")
    conns = {c["recurso"]: c for c in cat["conexoes"]}
    for k, g in gab["conexoes"].items():
        c = conns.get(k)
        if not c or c["status"] != g["status"] or c["usada_por"] != g["usada_por"]:
            out.append(f"conexão {k}: {c and (c['status'], c['usada_por'])} ≠ {(g['status'], g['usada_por'])}")
    if set(conns) - set(gab["conexoes"]):
        out.append(f"conexões a mais: {sorted(set(conns) - set(gab['conexoes']))}")
    deps = [{"de": d["de"], "para": d["para"], "por": d["por"]} for d in cat["dependencias"]]
    if deps != gab["dependencias"]:
        out.append(f"dependências {deps} ≠ {gab['dependencias']}")
    return out


# ------------------------------------------------------------------ 1. gabarito
cat = cl.montar()
dif = diferencas(cat, GAB)
confere(not dif, "gabarito: " + "; ".join(dif))
confere(cat["data_referencia"] == GAB["data_referencia"], f"data de referência {cat['data_referencia']}")
for n, it in por_nome(cat).items():  # nenhuma situação sem motivo: Crítico/Atenção sempre com sinal ou achado
    if it["situacao"] in ("Crítico", "Atenção"):
        confere(it["sinais"] or it["achados"], f"{n}: {it['situacao']} sem nenhum sinal ou achado")

# ------------------------------------------------------------------ 2. casos sintéticos
REL = "lgc-relatorio-custos"


def caso(muda):
    d = copy.deepcopy(BASE)
    muda(d)
    return por_nome(com_dados(d))[REL]


def sinais(it):
    return sorted(s["sinal"] for s in it["sinais"])


def parada(d):  # roda todo dia, mas a última execução foi há 5 dias
    dias = d["logicapps"][REL]["execucoes_por_dia"]
    for k in [k for k in dias if k > "2026-11-20"]:
        dias[k] = {}
    d["logicapps"][REL]["ultimas_execucoes"] = [{"inicio": "2026-11-20T10:00:00Z", "status": "Succeeded"}]


it = caso(parada)
confere("PARADA" in sinais(it) and it["situacao"] == "Crítico", f"parada há 5 dias (todo dia): {sinais(it)}")


def um_dia(d):  # rodou ontem: ainda dentro do limite de 2 dias
    d["logicapps"][REL]["ultimas_execucoes"] = [{"inicio": "2026-11-24T10:00:00Z", "status": "Succeeded"}]


confere("PARADA" not in sinais(caso(um_dia)), "1 dia sem rodar não é parada")


def desabilitada(d):
    parada(d)
    d["logicapps"][REL]["estado"] = "Disabled"


it = caso(desabilitada)
confere("DESABILITADA" in sinais(it) and "PARADA" not in sinais(it), f"desabilitada não é 'parada': {sinais(it)}")


def falhas_n(n):
    def muda(d):
        dias = d["logicapps"][REL]["execucoes_por_dia"]
        for i, k in enumerate(sorted(dias)):
            dias[k] = {"Failed": 1} if i < n else {"Succeeded": 1}
    return muda


confere(sinais(caso(falhas_n(3))) == ["FALHANDO"], f"3 de 30 (10%) é FALHANDO: {sinais(caso(falhas_n(3)))}")
confere(sinais(caso(falhas_n(2))) == ["FALHAS_PONTUAIS"], f"2 de 30 (6,7%) é FALHAS_PONTUAIS: {sinais(caso(falhas_n(2)))}")
it = caso(falhas_n(0))
confere(sinais(it) == [] and it["situacao"] == "Crítico", "sem falhas: sem sinal, mas segue Crítico pelo achado Alta (segredo na URL)")


def sem_dono(d):
    d["logicapps"][REL]["tags"] = {}


confere("SEM_DONO" in sinais(caso(sem_dono)), "sem tag owner: SEM_DONO")


def sem_operacao(d):
    del d["logicapps"][REL]


it = caso(sem_operacao)
confere(it["situacao"] == "Sem dados" and it["sinais"] == [], "sem dados de operação: 'Sem dados' e nenhum sinal inventado")


def conexao_sumida(d):
    d["conexoes"] = {k: v for k, v in d["conexoes"].items() if not k.endswith("/office365")}


it = caso(conexao_sumida)
confere("CONEXAO_COM_ERRO" not in sinais(it) and any(c["status"] == "desconhecido" for c in it["conexoes"]),
        "conexão sem dado de status: 'desconhecido', não erro")

# ------------------------------------------------------------------ 3. sincronização real com Azure falso
CONN_ID = "/subscriptions/0000/resourceGroups/rg-teste/providers/Microsoft.Web/connections/office365"
RESPOSTAS = {
    "workflow": {"name": "la-precos-logicapps", "tags": {"owner": "gabriel", "app": "piloto"},
                 "properties": {"state": "Enabled", "parameters": {"$connections": {"value": {"office365": {"connectionId": CONN_ID}}},
                                                                    "segredo": {"value": "NAO-GUARDAR-PARAMETRO"}}}},
    "metrics": {"value": [
        {"name": {"value": "RunsSucceeded"}, "timeseries": [{"data": [{"timeStamp": "2026-11-23T00:00:00Z", "total": 1},
                                                                     {"timeStamp": "2026-11-24T00:00:00Z", "total": 0},
                                                                     {"timeStamp": "2026-11-25T00:00:00Z", "total": 1}]}]},
        {"name": {"value": "RunsFailed"}, "timeseries": [{"data": [{"timeStamp": "2026-11-24T00:00:00Z", "total": 1}]}]}]},
    "runs": {"value": [{"name": "r3", "properties": {"startTime": "2026-11-25T11:00:00Z", "status": "Succeeded"}},
                       {"name": "r2", "properties": {"startTime": "2026-11-24T11:00:00Z", "status": "Failed"}}]},
    "actions": {"value": [{"name": "Consultar_precos", "properties": {"status": "Failed", "code": "ServiceUnavailable"}},
                          {"name": "Resumo", "properties": {"status": "Skipped"}}]},
    "connection": {"properties": {"api": {"name": "office365"}, "displayName": "caixa de teste", "createdTime": "2026-11-01T00:00:00Z",
                                  "changedTime": "2026-11-20T00:00:00Z", "parameterValues": {"token": "NAO-GUARDAR-TOKEN"},
                                  "statuses": [{"status": "Error", "error": {"code": "Unauthenticated", "message": "expirou"}}]}},
}


class ArmFalso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path
        chave = ("connection" if "/connections/" in p else "metrics" if "/metrics" in p else
                 "actions" if "/actions" in p else "runs" if "/runs" in p else "workflow")
        corpo = json.dumps(RESPOSTAS[chave]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corpo)


srv = ThreadingHTTPServer(("127.0.0.1", 0), ArmFalso)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp(prefix="operacao-"))
az.ARM, az.SAIDA, az.CONFIG = f"http://127.0.0.1:{srv.server_address[1]}", tmp, tmp / "azure.json"
az.CONFIG.write_text(json.dumps({"assinatura": "0000", "grupo": "rg-teste", "nome": "la-precos-logicapps"}), encoding="utf-8")
az._token["v"] = "token-falso"
dados = az.operacao()
srv.shutdown()
arq = tmp / "la-precos-logicapps-operacao.json"
bruto = arq.read_text(encoding="utf-8") if arq.exists() else ""
confere(arq.exists(), "operacao() devia gravar relatorios/azure/<nome>-operacao.json")
confere("NAO-GUARDAR" not in bruto, "credencial da conexão ou valor de parâmetro foi gravado no arquivo")
confere(dados["execucoes_por_dia"] == {"2026-11-23": {"Succeeded": 1}, "2026-11-24": {"Failed": 1}, "2026-11-25": {"Succeeded": 1}},
        f"execuções por dia lidas das métricas: {dados['execucoes_por_dia']}")
confere(dados["ultimas_execucoes"][1].get("acao_com_falha") == "Consultar_precos" and
        dados["ultimas_execucoes"][1].get("codigo") == "ServiceUnavailable", f"ação que falhou: {dados['ultimas_execucoes']}")
confere(dados["conexoes"][CONN_ID]["status"] == "Error" and dados["conexoes"][CONN_ID]["erro"]["codigo"] == "Unauthenticated",
        f"status da conexão: {dados['conexoes']}")
cl.OPERACAO_REAL = tmp
real = por_nome(cl.montar())["la-precos-logicapps"]
cl.OPERACAO_REAL = VAZIA
confere(real["origem_operacao"] == "medido no Azure" and real["dono"] == "gabriel" and real["operacao"]["execucoes_30d"] == 3
        and real["operacao"]["falhas_30d"] == 1, f"catálogo com a Logic App real: {real['operacao']} dono={real['dono']}")
confere([(c["chave"], c["status"]) for c in real["conexoes"]] == [("office365", "Error")] and "CONEXAO_COM_ERRO" in sinais(real),
        f"conexão da Logic App real (vem do Azure, a definição baixada não guarda parâmetros): {real['conexoes']}")

# ------------------------------------------------------------------ 4. página
md = cl.markdown(cat)
citadas = set(re.findall(r"\[\[([^\]]+)\]\]", md)) - {"INDICE Logic Apps"}
nomes = {x["nome"] for x in cat["logicapps"]}
confere(citadas <= nomes, f"a página cita Logic Apps que não existem: {sorted(citadas - nomes)}")
confere(nomes <= citadas, f"a página deixou Logic Apps de fora: {sorted(nomes - citadas)}")
confere("8.640" in md and "26,7%" in md and "sem dono" in md, "a página devia trazer os números e o 'sem dono'")

# ------------------------------------------------------------------ 5. sabotagem
d = copy.deepcopy(BASE)
d["logicapps"][REL]["execucoes_por_dia"]["2026-11-24"] = {"Succeeded": 1}  # some uma falha
confere(any("lgc-relatorio-custos: falhas_30d 3 ≠ 4" in x for x in diferencas(com_dados(d), GAB)),
        "sabotagem: com uma falha a menos, a comparação com o gabarito devia reprovar")
d = copy.deepcopy(BASE)
d["conexoes"][next(k for k in d["conexoes"] if k.endswith("/sharepointonline"))]["status"] = "Connected"
confere(diferencas(com_dados(d), GAB), "sabotagem: com a conexão do SharePoint consertada, o gabarito devia reprovar")

total = ok + len(falhas)
print(f"Catálogo de automações: {ok}/{total} verificações")
for f in falhas:
    print("  FALHOU:", f)
print("\nRESULTADO:", "CATÁLOGO CORRETO" if not falhas else f"REPROVADO ({len(falhas)} problema(s))")
sys.exit(0 if not falhas else 1)
