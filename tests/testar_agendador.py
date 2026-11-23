"""Testa a sincronização agendada sem Azure, sem Windows e sem Docker.

  1. comando do Agendador de Tarefas do Windows (schtasks /create, conforme a doc oficial);
  2. uma rodada: ordem das tarefas, parada no primeiro erro e estado gravado (última e próxima rodada);
  3. carga no Postgres guarda o histórico: execuções e métricas com ON CONFLICT (sem apagar as antigas),
     uma linha por sincronização com o intervalo do agendador, simuladas removidas;
  4. diagnóstico do chamado "sincronização atrasada" aponta o passo que falhou.

Uso:  python tests/testar_agendador.py      Termina com "RESULTADO: AGENDADOR CORRETO".
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="agendador-"))
os.environ["PILOTO_HISTORICO"] = str(TMP / "historico.jsonl")
os.environ["PILOTO_AGENDADOR_ESTADO"] = str(TMP / "agendador.json")
os.environ["PILOTO_AZURE_DIR"] = str(TMP / "azure")
os.environ["PILOTO_CHAMADOS_DIR"] = str(TMP / "chamados")
sys.path.insert(0, str(ROOT / "tools"))
import agendador as ag  # noqa: E402
import carregar_grafana as cg  # noqa: E402
import receptor_chamados as rc  # noqa: E402
import rodar  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
ok, falhas = 0, []


def confere(cond, msg):
    global ok
    if cond:
        ok += 1
    else:
        falhas.append(msg)


# 1. schtasks
cmd = ag.comando_tarefa(python=r"C:\Python313\python.exe", script=r"C:\Users\x\Área de Trabalho\proj\tools\agendador.py")
confere(cmd.startswith('"C:\\Python313\\python') and '"' + r"C:\Users\x\Área de Trabalho\proj\tools\agendador.py" + '"' in cmd
        and cmd.endswith("--uma-vez --registrar-log"), f"comando com aspas nos caminhos com espaço: {cmd}")
a6 = ag.args_schtasks_criar(6, "X")
confere(a6 == ["schtasks", "/create", "/tn", ag.NOME_TAREFA, "/tr", "X", "/sc", "hourly", "/mo", "6", "/it", "/f"],
        f"a cada 6 h: {a6}")
a48 = ag.args_schtasks_criar(48, "X")
confere(a48[6:10] == ["/sc", "daily", "/mo", "2"], f"a cada 48 h vira diário a cada 2 dias: {a48}")
for ruim in (0, 25, -3):
    try:
        ag.args_schtasks_criar(ruim, "X")
        confere(False, f"intervalo {ruim} h devia ser recusado (schtasks aceita 1-23 h ou dias)")
    except ValueError:
        confere(True, "")

# 2. uma rodada (as tarefas reais são trocadas por falsas)
chamadas = []


def rodar_falso(resultado):
    def f(t, origem="terminal", ao_vivo=False):
        chamadas.append((t, origem))
        return "id", resultado[t], f"resumo {t}"
    return f


rodar.rodar = rodar_falso({"azure": True, "grafana": True})
confere(ag.uma_rodada(6) is True, "rodada com tudo certo devolveu falha")
confere(chamadas == [("azure", "agendador"), ("grafana", "agendador")], f"ordem/origem das tarefas: {chamadas}")
e = ag.ler_estado()
proxima = datetime.fromisoformat(e["proxima_estimada"]) - datetime.fromisoformat(e["ultima_rodada"])
confere(e["ultimo_resultado"] == "ok" and e["a_cada_h"] == 6 and abs(proxima - timedelta(hours=6)) < timedelta(seconds=2),
        f"estado depois da rodada: {e}")
chamadas.clear()
rodar.rodar = rodar_falso({"azure": False, "grafana": True})
confere(ag.uma_rodada(6) is False, "rodada com Azure falhando devolveu sucesso")
confere(chamadas == [("azure", "agendador")], f"com o Azure falhando não pode carregar dado velho no Grafana: {chamadas}")
confere(ag.ler_estado()["ultimo_resultado"] == "falhou", "estado não registrou a falha")

# 3. carga com histórico
az = Path(os.environ["PILOTO_AZURE_DIR"])
az.mkdir(parents=True)
la = "la-precos-logicapps"  # a definição real está em logicapps/reais/ (usada para o previsto)
ate = "2026-11-20T12:00:00+00:00"
(az / f"{la}-execucoes.json").write_text(json.dumps([
    {"execucao": "run-1", "status": "Succeeded", "inicio": "2026-11-20T10:00:00Z", "fim": "2026-11-20T10:00:05Z",
     "acoes": {"A": "Succeeded"}},
    {"execucao": "run-2", "status": "Failed", "inicio": "2026-11-20T11:00:00Z", "fim": "2026-11-20T11:00:05Z",
     "acoes": {"A": "Failed"}}]), encoding="utf-8")
(az / f"{la}-metricas.json").write_text(json.dumps({"de": "2026-11-13T12:00:00+00:00", "ate": ate,
    "totais": {"BillableActionExecutions": 30, "BillableTriggerExecutions": 2}, "bruto": {"value": []}}), encoding="utf-8")
sql, resumo = cg.montar_sql()
confere("TRUNCATE azure_precos, azure_previsto, historico, chamados;" in sql and "TRUNCATE azure_execucoes" not in sql
        and "azure_metricas," not in sql.split("TRUNCATE", 1)[1].split(";", 1)[0], "carga não pode apagar execuções e métricas")
confere("DELETE FROM azure_execucoes WHERE simulada;" in sql, "carga tem que tirar as execuções simuladas")
confere("ON CONFLICT (execucao) DO UPDATE SET" in sql, "execuções sem ON CONFLICT (duplicaria ou falharia)")
confere("ON CONFLICT (logic_app, sincronizado_em) DO NOTHING" in sql, "sincronização sem ON CONFLICT")
linha = next((l for l in sql.splitlines() if l.startswith("('la-precos-logicapps', '2026-11-20T12:00:00+00:00'")), "")
confere(", 2, 1, " in linha and ", 15.0, " in linha and ", 6) ON CONFLICT" in linha,
        f"linha da sincronização (2 execuções, 1 falha, intervalo 6 h): {linha}")
confere("azure_sincronizacoes" in sql.split("GRANT SELECT ON", 1)[1].split("TO", 1)[0], "leitor do Grafana sem acesso à tabela nova")

# 4. diagnóstico do chamado
ag.grava_estado(a_cada_h=6, ultima_rodada="2026-11-20T09:00:00-03:00", ultimo_resultado="falhou",
                passos=[{"tarefa": "azure", "ok": False, "resumo": "ERRO: az login expirado"}])
prio, linhas, passos = rc.diag_sincronizacao_atrasada(la, {})
confere(prio == "Média", f"prioridade {prio}")
confere(any("az login expirado" in l for l in linhas), f"diagnóstico não mostra o passo que falhou: {linhas}")
confere(any("a cada 6 h" in l for l in linhas), "diagnóstico não mostra o intervalo")
confere(any("az account show" in p for p in passos), "próximos passos sem conferir o login da Azure CLI")
alerta = {"status": "firing", "labels": {"alertname": "Sincronizacao agendada atrasada", "regra": "sincronizacao_atrasada",
                                         "logic_app": la}, "annotations": {"description": "teste"}, "fingerprint": "sinc"}
res = rc.processar({"alerts": [alerta]})
confere(res and res[0][0] == "criado", f"alerta de sincronização atrasada não abriu chamado: {res}")
if res and res[0][1]:
    c = json.loads((rc.PASTA / f"{res[0][1]}.json").read_text(encoding="utf-8"))
    confere(c["componente"] == "Integração com o Azure", f"componente: {c['componente']}")

total = ok + len(falhas)
print(f"Teste do agendador: {ok}/{total} verificações")
for f in falhas:
    print("  FALHOU:", f)
print("\nRESULTADO:", "AGENDADOR CORRETO" if not falhas else f"REPROVADO ({len(falhas)} problema(s))")
sys.exit(0 if not falhas else 1)
