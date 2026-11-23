"""Teste de ponta a ponta do ambiente Docker (Postgres + Grafana + receptor de alertas).

Precisa do ambiente no ar:  docker compose up -d
Confere, pela API do Grafana e do receptor, que:
  1. o Grafana subiu e o datasource conecta no Postgres;
  2. os 2 painéis e as 3 regras de alerta foram provisionados pelos arquivos;
  3. o usuário só-leitura do Grafana enxerga os dados de custo e as tabelas do piloto;
  4. um alerta de verdade dispara no Grafana, vai ASSINADO (HMAC) e o receptor abre o chamado certo;
     alerta sem assinatura é recusado;
  5. o hub (container) responde, só aceita execução vinda da própria página e roda uma tarefa de verdade
     (carregar os dados no Postgres pelo psql do container);
  6. o Postgres guarda o histórico das sincronizações (duas cargas seguidas somam, não substituem) e o alerta
     "sincronização atrasada" abre chamado quando passam mais de 2 intervalos do agendador sem sincronizar.

Uso:  python tests/testar_ambiente.py            (espera até 4 min pelo alerta)
Termina com "RESULTADO: AMBIENTE OK" ou "RESULTADO: AMBIENTE COM PROBLEMAS".
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAFANA = os.environ.get("GRAFANA_URL", "http://localhost:3000")
RECEPTOR = os.environ.get("RECEPTOR_URL_LOCAL", "http://localhost:8088")
HUB = os.environ.get("HUB_URL", "http://localhost:8090")
AUTH = "Basic " + base64.b64encode(os.environ.get("GRAFANA_AUTH", "admin:admin").encode()).decode()
CHAMADOS = Path(os.environ.get("PILOTO_CHAMADOS_DIR", ROOT / "chamados"))
ESPERA_ALERTA_S = int(os.environ.get("ESPERA_ALERTA_S", "240"))

falhas = []


def confere(ok, msg):
    print(("  OK    " if ok else "  FALHA ") + msg)
    if not ok:
        falhas.append(msg)
    return ok


def chama(url, corpo=None, auth=True, cabecalhos=None, metodo=None):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode() if corpo is not None else None, method=metodo,
                                 headers={"Content-Type": "application/json", **({"Authorization": AUTH} if auth else {}),
                                          **(cabecalhos or {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def get_status(url, cabecalhos=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=cabecalhos or {}), timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def status_de(url, corpo=None, cabecalhos=None):
    try:
        chama(url, corpo, auth=False, cabecalhos=cabecalhos, metodo="POST")
        return 200
    except urllib.error.HTTPError as e:
        return e.code


def espera(titulo, teste, limite_s, passo_s=5):
    t0 = time.time()
    while True:
        try:
            r = teste()
            if r:
                return r
        except (urllib.error.URLError, ConnectionError, ValueError, OSError):
            pass
        if time.time() - t0 > limite_s:
            return None
        print(f"  ...    aguardando {titulo} ({int(time.time() - t0)} s)")
        time.sleep(passo_s)


def consulta_sql(sql):
    corpo = {"queries": [{"refId": "A", "datasource": {"uid": "focus-pg", "type": "grafana-postgresql-datasource"},
                          "rawSql": sql, "format": "table"}], "from": "now-1h", "to": "now"}
    r = chama(f"{GRAFANA}/api/ds/query", corpo)
    frame = r["results"]["A"]["frames"][0]
    return frame["data"]["values"][0][0]


LA_TESTE = "teste-historico"


def carga(pasta_azure, estado):
    env = {**os.environ, "PILOTO_AZURE_DIR": str(pasta_azure), "PILOTO_AGENDADOR_ESTADO": str(estado),
           "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "carregar_grafana.py")], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1:]


def historico_sincronizacoes():
    """Duas sincronizações falsas (Logic App 'teste-historico', agendador a cada 1 h, última há 4 h)."""
    sys.path.insert(0, str(ROOT / "tools"))
    import carregar_grafana as cg
    tmp = Path(tempfile.mkdtemp(prefix="sinc-"))
    estado = tmp / "agendador.json"
    estado.write_text(json.dumps({"a_cada_h": 1}), encoding="utf-8")
    agora = datetime.now(timezone.utc)
    try:
        for i, (execucao, horas_atras) in enumerate((("teste-run-1", 5), ("teste-run-2", 4)), 1):
            momento = (agora - timedelta(hours=horas_atras)).isoformat(timespec="seconds")
            (tmp / f"{LA_TESTE}-execucoes.json").write_text(json.dumps([
                {"execucao": execucao, "status": "Succeeded", "inicio": momento, "fim": momento, "acoes": {"A": "Succeeded"}}]),
                encoding="utf-8")
            (tmp / f"{LA_TESTE}-metricas.json").write_text(json.dumps({"ate": momento, "totais": {}, "bruto": {"value": []}}),
                                                           encoding="utf-8")
            ok, saida = carga(tmp, estado)
            confere(ok, f"carga {i} da sincronização falsa: {saida}")
        n_exec = consulta_sql(f"SELECT count(*) FROM azure_execucoes WHERE logic_app = '{LA_TESTE}'")
        n_sinc = consulta_sql(f"SELECT count(*) FROM azure_sincronizacoes WHERE logic_app = '{LA_TESTE}'")
        confere(n_exec == 2, f"execuções acumuladas: 2 cargas com 1 execução cada → {n_exec} no Postgres")
        confere(n_sinc == 2, f"sincronizações registradas: {n_sinc} (esperado 2)")

        def chamado_atrasada():
            for p in sorted(CHAMADOS.glob("CH-*.json")):
                c = json.loads(p.read_text(encoding="utf-8"))
                if c.get("regra") == "sincronizacao_atrasada" and c.get("alvo") == LA_TESTE:
                    return c
            return None
        c = espera("o alerta 'sincronização atrasada' (4 h sem sincronizar, agendado a cada 1 h)", chamado_atrasada,
                   ESPERA_ALERTA_S, 10)
        if confere(bool(c), "chamado aberto pelo alerta de sincronização atrasada"):
            confere(c["componente"] == "Integração com o Azure" and c["prioridade"] == "Média",
                    f"componente {c['componente']}, prioridade {c['prioridade']}")
    finally:  # tira os dados de teste e recarrega os dados reais
        r = subprocess.run(cg.psql_cmd() + ["-q", "-c", f"DELETE FROM azure_execucoes WHERE logic_app = '{LA_TESTE}'; "
                                            f"DELETE FROM azure_sincronizacoes WHERE logic_app = '{LA_TESTE}';"],
                           cwd=ROOT, capture_output=True)
        confere(r.returncode == 0, "limpeza dos dados de teste no Postgres")
        subprocess.run([sys.executable, str(ROOT / "tools" / "carregar_grafana.py")], cwd=ROOT, capture_output=True)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("1. Grafana e datasource")
    saude = espera("o Grafana responder", lambda: chama(f"{GRAFANA}/api/health", auth=False), 120)
    if not confere(bool(saude) and saude.get("database") == "ok", f"Grafana no ar ({(saude or {}).get('version', '?')})"):
        print("RESULTADO: AMBIENTE COM PROBLEMAS")
        return 1
    ds = espera("o datasource conectar", lambda: chama(f"{GRAFANA}/api/datasources/uid/focus-pg/health"), 60)
    confere(bool(ds) and ds.get("status") == "OK", "datasource Postgres conecta")

    print("2. Provisionamento (arquivos em grafana/provisioning)")
    paineis = {d["uid"] for d in chama(f"{GRAFANA}/api/search?type=dash-db")}
    for uid in ("finops-custos-demo", "piloto-operacao"):
        confere(uid in paineis, f"painel {uid}")
    regras = {r["uid"]: r for r in chama(f"{GRAFANA}/api/v1/provisioning/alert-rules")}
    for uid in ("piloto-recurso-sem-dono", "piloto-logicapp-falha", "piloto-custo-divergente"):
        confere(uid in regras, f"regra de alerta {uid}")
    contatos = chama(f"{GRAFANA}/api/v1/provisioning/contact-points")
    confere(any((c.get("settings") or {}).get("url", "").endswith("/alerta") for c in contatos), "contact point aponta para o receptor")

    print("3. Dados vistos pelo usuário só-leitura do Grafana")
    linhas = consulta_sql("SELECT count(*) FROM focus_costs")
    confere(linhas > 0, f"focus_costs tem {linhas} linhas")
    for tabela in ("historico", "chamados", "azure_execucoes", "azure_previsto"):
        try:
            consulta_sql(f"SELECT count(*) FROM {tabela}")
            confere(True, f"tabela {tabela} acessível")
        except (urllib.error.HTTPError, KeyError, IndexError) as e:
            confere(False, f"tabela {tabela} acessível ({e})")

    print("4. Alerta de verdade → chamado (assinado)")
    confere(bool(chama(f"{RECEPTOR}/", auth=False)), "receptor no ar")
    falso = {"status": "firing", "alerts": [{"status": "firing", "labels": {"alertname": "x", "regra": "recurso_sem_dono"},
                                             "fingerprint": "falso"}]}
    confere(status_de(f"{RECEPTOR}/alerta", falso) == 401, "receptor recusa alerta sem assinatura (401)")
    confere(status_de(f"{RECEPTOR}/alerta", falso, {"X-Grafana-Alerting-Signature": "0" * 64,
                                                    "X-Grafana-Alerting-Signature-Timestamp": str(int(time.time()))}) == 401,
            "receptor recusa assinatura falsa (401)")

    def chamado_sem_dono():
        for p in sorted(CHAMADOS.glob("CH-*.json")):
            c = json.loads(p.read_text(encoding="utf-8"))
            if c.get("regra") == "recurso_sem_dono":
                return c
        return None

    c = espera("o Grafana disparar o alerta 'recurso sem dono'", chamado_sem_dono, ESPERA_ALERTA_S, 10)
    if confere(bool(c), "chamado aberto pelo alerta do Grafana"):
        confere(c["alvo"] == "stgbackupantigo", f"alvo do chamado: {c['alvo']}")
        confere(c["prioridade"] == "Alta" and c["status"] == "Aberto", f"prioridade {c['prioridade']}, status {c['status']}")
        confere(any("sem a tag `owner`" in d for d in c["diagnostico"]), "diagnóstico calculado em código")
        confere(c["origem"].startswith("Alerta do Grafana"), "origem: Grafana")
        confere(not any(p.read_text(encoding="utf-8").count('"falso"') for p in CHAMADOS.glob("CH-*.json")),
                "nenhum chamado veio do alerta sem assinatura")

    print("5. Hub no container")
    est = espera("o hub responder", lambda: chama(f"{HUB}/api/estado", auth=False), 60)
    if confere(bool(est), "hub no ar"):
        confere(est["servicos"] == {"grafana": True, "receptor": True}, f"hub enxerga Grafana e receptor: {est['servicos']}")
        confere(est["grafana"]["url"].startswith("http://localhost"), f"painéis apontam para o navegador: {est['grafana']['url']}")
        tarefas = {t["id"]: t for t in est["tarefas"]}
        if os.environ.get("HUB_EM_CONTAINER", "1") == "1":
            confere(bool(tarefas["azure"]["indisponivel"]), "tarefa Azure aparece como 'só no PC' (sem az no container)")
        confere(status_de(f"{HUB}/api/executar/grafana") == 403, "hub recusa execução sem o cabeçalho da página (403)")
        confere(status_de(f"{HUB}/api/executar/grafana", cabecalhos={"X-Piloto-Hub": "1", "Host": "exemplo.com"}) == 403,
                "hub recusa execução com Host de fora (403)")
        for proibido in ("config/azure.json", ".env", ".git/config"):
            confere(get_status(f"{HUB}/ver?arquivo={proibido}") == 404, f"hub não mostra {proibido}")
        confere(get_status(f"{HUB}/api/estado", {"Host": "exemplo.com"}) == 403, "hub recusa leitura com Host de fora (DNS rebinding)")
        inicio = time.time()
        confere(status_de(f"{HUB}/api/executar/grafana", cabecalhos={"X-Piloto-Hub": "1"}) == 200, "hub aceita execução da página")

        def carga_concluida():
            for h in chama(f"{HUB}/api/estado", auth=False)["historico"]:
                if h.get("tarefa") == "Carregar dados no Grafana" and h.get("origem") == "hub" and h.get("status") != "em andamento":
                    try:
                        if datetime.fromisoformat(h["inicio"]).timestamp() >= inicio - 5:
                            return h
                    except (KeyError, ValueError):
                        pass
            return None
        h = espera("a tarefa rodar no hub", carga_concluida, 90)
        confere(bool(h) and h["status"] == "ok", f"tarefa rodou pelo hub com psql do container: {(h or {}).get('resumo')}")

    print("6. Histórico das sincronizações e alerta de sincronização atrasada")
    historico_sincronizacoes()

    print()
    if falhas:
        print(f"{len(falhas)} problema(s).")
        print("RESULTADO: AMBIENTE COM PROBLEMAS")
        return 1
    print("RESULTADO: AMBIENTE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
