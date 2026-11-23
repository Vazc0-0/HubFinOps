"""Testa o receptor de alertas (tools/receptor_chamados.py) com alertas REAIS do Grafana 12.

Os arquivos em tests/casos_chamados/ foram capturados do Grafana 12.0.0 de verdade (webhook do contact point
provisionado em grafana/provisioning/alerting/): um alerta de recurso sem dono, um de Logic App com falha e o
aviso de "resolvido". O gabarito abaixo foi escrito à mão a partir dos dados do piloto.

Confere: chamado criado com título, prioridade, componente e diagnóstico certos; alerta repetido não duplica;
"resolvido" fecha o chamado; alerta que não é do piloto é ignorado; o servidor HTTP responde ao POST do Grafana.
Roda em pasta temporária: não mexe nos chamados nem no histórico de verdade.

Uso:  python tests/testar_chamados.py
"""
import copy
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="chamados-teste-"))
os.environ["PILOTO_CHAMADOS_DIR"] = str(TMP / "chamados")
os.environ["PILOTO_HISTORICO"] = str(TMP / "historico.jsonl")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import carregar_grafana as cg  # noqa: E402
import receptor_chamados as r  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
CASOS = ROOT / "tests" / "casos_chamados"
ok, falhas = 0, []


def confere(cond, msg):
    global ok
    if cond:
        ok += 1
    else:
        falhas.append(msg)


def carrega(nome):
    return json.loads((CASOS / nome).read_text(encoding="utf-8"))


def chamado(id_):
    return json.loads((r.PASTA / f"{id_}.json").read_text(encoding="utf-8"))


def tem(c, trecho):
    return any(trecho in l for l in c["diagnostico"])


# 1. recurso sem dono (alerta real do Grafana)
res = r.processar(carrega("grafana12_recurso_sem_dono.json"))
confere(len(res) == 1 and res[0][0] == "criado", f"recurso sem dono: esperado 1 chamado criado, veio {res}")
c1 = chamado(res[0][1])
confere(c1["titulo"] == "Recurso sem dono gerando custo: stgbackupantigo", f"título: {c1['titulo']}")
confere(c1["prioridade"] == "Alta", f"prioridade: {c1['prioridade']}")
confere(c1["componente"] == "FinOps", f"componente: {c1['componente']}")
confere(c1["status"] == "Aberto", f"status: {c1['status']}")
for trecho in ("sem a tag `owner`", "Storage, grupo `rg-dados`", "desde 01/09/2026", "R$ 732,00", "prioridade Alta"):
    confere(tem(c1, trecho), f"diagnóstico do recurso sem dono não tem '{trecho}'")
confere((r.PASTA / f"{c1['id']}.md").exists(), "faltou o .md do chamado")

# 2. o Grafana reenvia o mesmo alerta: não pode duplicar
res = r.processar(carrega("grafana12_recurso_sem_dono.json"))
confere(res == [("já existe", c1["id"])], f"alerta repetido duplicou: {res}")

# 3. Logic App com falha (alerta real); a execução com falha vem da sincronização (aqui, fixa)
r._execucoes = lambda la: ([], [{"logic_app": la, "execucao": "SIMULADA-TESTE", "status": "Failed",
                                 "inicio": "2026-11-06T12:54:58-03:00", "fim": "2026-11-06T12:54:58-03:00",
                                 "acoes": {"Inicializar_linhas": "Succeeded", "Tentar": "Failed",
                                           "Consultar_precos": "Failed", "Registrar_falha": "Succeeded",
                                           "Encerrar_com_falha": "Succeeded"}}])
res = r.processar(carrega("grafana12_logicapp_falha.json"))
confere(len(res) == 1 and res[0][0] == "criado", f"falha da Logic App: {res}")
c2 = chamado(res[0][1])
confere(c2["titulo"] == "Logic App com execução que falhou: la-precos-logicapps", f"título: {c2['titulo']}")
confere(c2["prioridade"] == "Alta" and c2["componente"] == "Logic Apps", f"prioridade/componente: {c2['prioridade']}/{c2['componente']}")
for trecho in ("SIMULADA para teste", "`Tentar`, `Consultar_precos`", "passo 2.1", "prices.azure.com",
               "exponential, 3 tentativas", "`Registrar_falha` roda quando há falha"):
    confere(tem(c2, trecho), f"diagnóstico da falha não tem '{trecho}'")

# 4. "resolvido" (real) fecha o chamado da falha e não mexe no outro
res = r.processar(carrega("grafana12_logicapp_resolvido.json"))
confere(res == [("resolvido", c2["id"])], f"resolvido: {res}")
confere(chamado(c2["id"])["status"] == "Resolvido" and chamado(c2["id"]).get("resolvido_em"), "chamado não foi fechado")
confere(chamado(c1["id"])["status"] == "Aberto", "o chamado do recurso sem dono foi fechado por engano")

# 5. custo divergente (mesmo formato do Grafana, regra trocada); previsão fixa para o teste
div = copy.deepcopy(carrega("grafana12_logicapp_falha.json"))
al = div["alerts"][0]
al["labels"].update({"alertname": "Custo medido diferente do previsto", "regra": "custo_divergente", "severidade": "media"})
al["fingerprint"], al["values"] = "teste-divergente", {"A": 2, "B": 1}
cg.previsto_x_medido = lambda la, dados=None: {"previsto_por_execucao": 15, "fixas": 8, "por_item": 1,
                                                "itens_no_loop": 7, "medido_acoes": 34, "medido_disparos": 2,
                                                "medido_por_execucao": 17.0}
res = r.processar(div)
c3 = chamado(res[0][1]) if res and res[0][0] == "criado" else {"diagnostico": [], "prioridade": None}
confere(c3["prioridade"] == "Média", f"custo divergente: prioridade {c3['prioridade']}")
for trecho in ("previu **15 ações", "**17 por execução**"):
    confere(tem(c3, trecho), f"diagnóstico do custo divergente não tem '{trecho}'")

# 6. alerta que não é do piloto (ex.: erro de fonte de dados do próprio Grafana) é ignorado
outro = copy.deepcopy(carrega("grafana12_recurso_sem_dono.json"))
outro["alerts"][0]["labels"] = {"alertname": "DatasourceError"}
outro["alerts"][0]["fingerprint"] = "outro"
confere(r.processar(outro) == [("ignorado", None)], "alerta de fora do piloto não foi ignorado")

# 7. servidor HTTP: o Grafana faz POST /alerta
srv = r.ThreadingHTTPServer(("127.0.0.1", 0), r.Receptor)
threading.Thread(target=srv.serve_forever, daemon=True).start()
novo = copy.deepcopy(carrega("grafana12_recurso_sem_dono.json"))
novo["alerts"][0]["fingerprint"] = "via-http"
req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/alerta", data=json.dumps(novo).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=10) as resp:
    corpo = json.loads(resp.read().decode())
confere(resp.status == 200 and corpo["resultado"][0][0] == "criado", f"HTTP: {resp.status} {corpo}")
srv.shutdown()

# 7b. com segredo: só aceita alerta assinado pelo Grafana (HMAC-SHA256 com carimbo de tempo)
SEG = "segredo-de-teste-1234567890"
r.Receptor.segredo = SEG
srv = r.ThreadingHTTPServer(("127.0.0.1", 0), r.Receptor)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/alerta"


def posta(corpo, cabecalhos):
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json", **cabecalhos}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


assinado = copy.deepcopy(carrega("grafana12_recurso_sem_dono.json"))
assinado["alerts"][0]["fingerprint"] = "assinado"
corpo = json.dumps(assinado).encode()
agora = str(int(time.time()))
confere(posta(corpo, {}) == 401, "alerta sem assinatura foi aceito")
confere(posta(corpo, {r.CAB_ASSINATURA: r.assinar("outro-segredo-qualquer-123", corpo, agora), r.CAB_HORARIO: agora}) == 401,
        "alerta assinado com outro segredo foi aceito")
velho = str(int(time.time()) - 3600)
confere(posta(corpo, {r.CAB_ASSINATURA: r.assinar(SEG, corpo, velho), r.CAB_HORARIO: velho}) == 401,
        "alerta com carimbo de 1 h atrás (reenvio) foi aceito")
alterado = corpo.replace(b"stgbackupantigo", b"stgoutrorecurso")
confere(posta(alterado, {r.CAB_ASSINATURA: r.assinar(SEG, corpo, agora), r.CAB_HORARIO: agora}) == 401,
        "alerta alterado depois de assinado foi aceito")
confere(posta(corpo, {r.CAB_ASSINATURA: r.assinar(SEG, corpo, agora), r.CAB_HORARIO: agora}) == 200,
        "alerta assinado certo foi recusado")
ms = str(int(time.time() * 1000))
assinado["alerts"][0]["fingerprint"] = "assinado-ms"
corpo2 = json.dumps(assinado).encode()
confere(posta(corpo2, {r.CAB_ASSINATURA: r.assinar(SEG, corpo2, ms), r.CAB_HORARIO: ms}) == 200,
        "alerta assinado com carimbo em milissegundos foi recusado")
srv.shutdown()
r.Receptor.segredo = None

# 8. tudo registrado no histórico (o que o hub mostra)
hist = [json.loads(l) for l in (TMP / "historico.jsonl").read_text(encoding="utf-8").splitlines()]
criados = {h["resumo"].split()[0] for h in hist if h.get("status") == "ok" and h.get("resumo", "").startswith("CH-")}
confere(len(criados) == 6, f"histórico: esperados 6 chamados registrados, vieram {len(criados)}")

total = ok + len(falhas)
print(f"Teste do receptor de alertas: {ok}/{total} verificações")
for f in falhas:
    print("  FALHOU:", f)
print("\nRESULTADO:", "CHAMADOS CORRETOS" if not falhas else f"REPROVADO ({len(falhas)} problema(s))")
sys.exit(0 if not falhas else 1)
