"""Teste de ponta a ponta do ambiente Docker (Postgres + Grafana + receptor de alertas).

Precisa do ambiente no ar:  docker compose up -d
Confere, pela API do Grafana e do receptor, que:
  1. o Grafana subiu e o datasource conecta no Postgres;
  2. os 2 painéis e as 3 regras de alerta foram provisionados pelos arquivos;
  3. o usuário só-leitura do Grafana enxerga os dados de custo e as tabelas do piloto;
  4. um alerta de verdade dispara no Grafana e o receptor abre o chamado certo, com diagnóstico.

Uso:  python tests/testar_ambiente.py            (espera até 4 min pelo alerta)
Termina com "RESULTADO: AMBIENTE OK" ou "RESULTADO: AMBIENTE COM PROBLEMAS".
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAFANA = os.environ.get("GRAFANA_URL", "http://localhost:3000")
RECEPTOR = os.environ.get("RECEPTOR_URL_LOCAL", "http://localhost:8088")
AUTH = "Basic " + base64.b64encode(os.environ.get("GRAFANA_AUTH", "admin:admin").encode()).decode()
CHAMADOS = Path(os.environ.get("PILOTO_CHAMADOS_DIR", ROOT / "chamados"))
ESPERA_ALERTA_S = int(os.environ.get("ESPERA_ALERTA_S", "240"))

falhas = []


def confere(ok, msg):
    print(("  OK    " if ok else "  FALHA ") + msg)
    if not ok:
        falhas.append(msg)
    return ok


def chama(url, corpo=None, auth=True):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": AUTH} if auth else {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8") or "null")


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

    print("4. Alerta de verdade → chamado")
    confere(bool(chama(f"{RECEPTOR}/", auth=False)), "receptor no ar")

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

    print()
    if falhas:
        print(f"{len(falhas)} problema(s).")
        print("RESULTADO: AMBIENTE COM PROBLEMAS")
        return 1
    print("RESULTADO: AMBIENTE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
