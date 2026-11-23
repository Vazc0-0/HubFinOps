"""Testa a comparação de versões de Logic Apps (tools/comparar_logicapp.py) com mudanças de gabarito.

Cada caso parte de uma Logic App de exemplo, aplica UMA mudança conhecida e confere que a comparação
aponta exatamente essa mudança (e nada além dela): gatilho, ação nova/removida/alterada, retentativa,
conector, tratamento de erro, segredo na URL e custo. Também testa a leitura das versões do Azure com
um servidor falso (sem Azure de verdade) e que o relatório não repete segredo.

Uso:  python tests/testar_comparacao.py      Termina com "RESULTADO: COMPARAÇÃO CORRETA".
"""
import copy
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import azure_logicapp as az  # noqa: E402
import comparar_logicapp as cmp  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
ok, falhas = 0, []


def confere(cond, msg):
    global ok
    if cond:
        ok += 1
    else:
        falhas.append(msg)


def exemplo(nome):
    return json.loads((ROOT / "logicapps" / "exemplos" / f"{nome}.json").read_text(encoding="utf-8-sig"))["definition"]


def so(r, **esperado):
    """Confere quantas ações novas/removidas/alteradas e se o gatilho mudou (o resto tem que ficar igual)."""
    real = {"novas": len(r["novas"]), "removidas": len(r["removidas"]), "alteradas": len(r["alteradas"]),
            "gatilho": r["gatilho"][0] != r["gatilho"][1]}
    alvo = {"novas": 0, "removidas": 0, "alteradas": 0, "gatilho": False, **esperado}
    return real == alvo, real


def codigos(lista):
    return {c for c, _, _ in lista}


custos = exemplo("lgc-relatorio-custos")
desvios = exemplo("lgc-desvios-processo")

# 0. versão igual: nada muda
r = cmp.comparar(custos, copy.deepcopy(custos))
igual, real = so(r)
confere(igual and not r["achados_novos"] and not r["achados_resolvidos"] and not r["atencao"], f"versão igual: {real} {r['atencao']}")
confere("Nenhuma mudança no fluxo" in cmp.relatorio("x", r), "relatório de versão igual não diz que nada mudou")

# 1. exemplo do projeto: recorrência 1 h → 5 min (anomalia A4)
v1, _ = cmp.carregar(ROOT / "logicapps" / "versoes" / "lgc-desvios-processo.v1.json")
r = cmp.comparar(v1, desvios)
igual, real = so(r, gatilho=True)
confere(igual, f"exemplo: só o gatilho muda ({real})")
confere(r["cobranca"]["execucoes_mes"] == (730.0, 8760.0), f"execuções/mês 730 → 8.760: {r['cobranca']['execucoes_mes']}")
confere(codigos(r["achados_novos"]) == {"RECORRENCIA_FREQUENTE"} and not r["achados_resolvidos"],
        f"exemplo: só RECORRENCIA_FREQUENTE aparece: {r['achados_novos']}")
confere(any("sobem 1100%" in x for x in r["atencao"]), f"exemplo: atenção ao aumento de ações por mês: {r['atencao']}")

# 2. ação nova (Compor no fim do fluxo)
b = copy.deepcopy(custos)
b["actions"]["Registrar_resumo"] = {"type": "Compose", "inputs": "@body('Ler_resposta')",
                                    "runAfter": {"Passou_do_limite": ["Succeeded"]}}
r = cmp.comparar(custos, b)
igual, real = so(r, novas=1)
confere(igual and r["novas"][0]["nome"] == "Registrar_resumo", f"ação nova: {real}")
confere(r["cobranca"]["fixas_por_execucao"][1] == r["cobranca"]["fixas_por_execucao"][0] + 1, "ação nova: +1 ação cobrada")

# 3. ação removida (a de fim de fluxo, ninguém depende dela)
r = cmp.comparar(b, custos)
igual, real = so(r, removidas=1)
confere(igual and r["removidas"][0]["nome"] == "Registrar_resumo", f"ação removida: {real}")

# 4. entrada alterada (o esquema do Analisar JSON)
b = copy.deepcopy(custos)
b["actions"]["Ler_resposta"]["inputs"]["schema"]["properties"]["moeda"] = {"type": "string"}
r = cmp.comparar(custos, b)
igual, real = so(r, alteradas=1)
confere(igual and r["alteradas"][0]["mudancas"] == ["entradas/configuração alteradas"], f"entrada alterada: {r['alteradas']}")

# 5. retentativa: none → padrão resolve o achado, sem acusar "entradas"
b = copy.deepcopy(custos)
del b["actions"]["Chamar_function_de_custos"]["inputs"]["retryPolicy"]
r = cmp.comparar(custos, b)
igual, real = so(r, alteradas=1)
confere(igual and r["alteradas"][0]["mudancas"] == ["retentativa: none → default"], f"retentativa: {r['alteradas']}")
confere(codigos(r["achados_resolvidos"]) == {"SEM_RETENTATIVA"} and not r["achados_novos"],
        f"retentativa resolvida: {r['achados_resolvidos']}")
r = cmp.comparar(b, custos)
confere(codigos(r["achados_novos"]) == {"SEM_RETENTATIVA"} and any("SEM_RETENTATIVA" in x for x in r["atencao"]),
        f"retentativa desligada vira risco novo e ponto de atenção: {r['achados_novos']} {r['atencao']}")

# 6. ordem: runAfter mudou
b = copy.deepcopy(custos)
b["actions"]["Passou_do_limite"]["runAfter"] = {"Ler_resposta": ["Succeeded", "Failed"]}
r = cmp.comparar(custos, b)
igual, real = so(r, alteradas=1)
confere(igual and r["alteradas"][0]["mudancas"][0].startswith("executa após:"), f"runAfter: {r['alteradas']}")

# 7. tratamento de erro novo resolve SEM_TRATAMENTO_DE_ERRO
b = copy.deepcopy(desvios)
b["actions"]["Avisar_falha"] = {"type": "Compose", "inputs": "falhou",
                                "runAfter": {"Para_cada_analista": ["Failed", "TimedOut"]}}
r = cmp.comparar(desvios, b)
confere("SEM_TRATAMENTO_DE_ERRO" in codigos(r["achados_resolvidos"]) and r["trata_erro"] == (False, True),
        f"tratamento de erro novo: {r['achados_resolvidos']} {r['trata_erro']}")
r = cmp.comparar(b, desvios)
confere(any("não tem mais tratamento de erro" in x for x in r["atencao"]), f"tratamento de erro removido: {r['atencao']}")

# 8. conector novo
b = copy.deepcopy(custos)
b["actions"]["Postar_no_Teams"] = {"type": "ApiConnection", "runAfter": {"Passou_do_limite": ["Succeeded"]},
                                   "inputs": {"host": {"connection": {"name": "@parameters('$connections')['teams']['connectionId']"}},
                                              "method": "post", "path": "/v3/beta/teams/x/channels/y/messages", "body": {}}}
r = cmp.comparar(custos, b)
confere(r["conectores"] == (["teams"], []) and any("Conector novo: Microsoft Teams" in x for x in r["atencao"]),
        f"conector novo: {r['conectores']} {r['atencao']}")

# 9. segredo na URL de uma ação nova: risco Alta e o relatório não repete a chave
b = copy.deepcopy(desvios)
b["actions"]["Chamar_api"] = {"type": "Http", "runAfter": {"Para_cada_analista": ["Succeeded"]},
                              "inputs": {"method": "GET", "uri": "https://exemplo.azurewebsites.net/api/x?code=SEGREDO-123"}}
r = cmp.comparar(desvios, b)
confere("SEGREDO_NA_URL" in codigos(r["achados_novos"]) and any("Risco novo (Alta): SEGREDO_NA_URL" in x for x in r["atencao"]),
        f"segredo na URL: {r['achados_novos']}")
confere("SEGREDO-123" not in cmp.relatorio("x", r), "o relatório repetiu o segredo da URL")

# 10. versões do Azure com servidor falso (sem Azure de verdade)
VERS = [{"name": "v-antiga", "properties": {"version": "085001", "changedTime": "2026-11-01T10:00:00Z",
                                            "definition": v1, "parameters": {"segredo": {"value": "NAO-GUARDAR"}}}},
        {"name": "v-nova", "properties": {"version": "085003", "changedTime": "2026-11-20T10:00:00Z", "definition": desvios}},
        {"name": "v-meio", "properties": {"version": "085002", "changedTime": "2026-11-10T10:00:00Z", "definition": v1}}]


class ArmFalso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        corpo = json.dumps({"value": VERS} if "/versions" in self.path else {"erro": self.path}).encode()
        self.send_response(200 if "/versions" in self.path else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corpo)


srv = ThreadingHTTPServer(("127.0.0.1", 0), ArmFalso)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp(prefix="versoes-"))
az.ARM, az.SAIDA, az.CONFIG = f"http://127.0.0.1:{srv.server_address[1]}", tmp, tmp / "azure.json"
az.CONFIG.write_text(json.dumps({"assinatura": "0000", "grupo": "rg-teste", "nome": "lgc-desvios-processo"}), encoding="utf-8")
az._token["v"] = "token-falso"
arqs = az.versoes()
confere([json.loads(a.read_text(encoding="utf-8"))["version"] for a in arqs] == ["085003", "085002", "085001"],
        f"versões em ordem da mais nova para a mais antiga: {[a.name for a in arqs]}")
confere(all("NAO-GUARDAR" not in a.read_text(encoding="utf-8") for a in arqs), "parâmetros da versão foram gravados (podem ter segredo)")
saida = tmp / "comparacao.md"
codigo = cmp.main(["azure", "--saida", str(saida)])
texto = saida.read_text(encoding="utf-8") if saida.exists() else ""
confere(codigo == 0 and "| Versão | 085002 | 085003 |" in texto and "a cada 5 minutos" in texto,
        "comparação azure: devia comparar as 2 versões mais novas (085002 → 085003)")
# 11. a versão de criação (vazia) não conta como mudança
VERS[:] = [{"name": "v-criacao", "properties": {"version": "085000", "changedTime": "2026-10-01T10:00:00Z",
                                               "definition": {"triggers": {}, "actions": {}}}}, VERS[1]]
saida2 = tmp / "comparacao2.md"
codigo = cmp.main(["azure", "--saida", str(saida2)])
confere(codigo == 0 and not saida2.exists(), "versão de criação vazia: não devia gerar comparação '0 → 12 ações novas'")
confere(cmp.main(["nao-existe-antes.json", "nao-existe-depois.json"]) == 1, "arquivo que não existe: devia avisar, não quebrar")
srv.shutdown()
os.environ.pop("AZURE_ARM_URL", None)

total = ok + len(falhas)
print(f"Teste da comparação de versões: {ok}/{total} verificações")
for f in falhas:
    print("  FALHOU:", f)
print("\nRESULTADO:", "COMPARAÇÃO CORRETA" if not falhas else f"REPROVADO ({len(falhas)} problema(s))")
sys.exit(0 if not falhas else 1)
