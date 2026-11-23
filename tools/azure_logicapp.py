"""Liga o projeto a uma Logic App REAL no Azure (somente leitura).

Usa a Azure CLI (`az`), já logada com `az login`, para chamar as APIs oficiais:
  - Workflows - Get ............ definição da Logic App
  - Workflow Runs - List ........ últimas execuções
  - Workflow Run Actions - List . status de cada ação em cada execução
  - Azure Monitor Metrics ...... BillableActionExecutions, BillableTriggerExecutions, TotalBillableExecutions
A Azure CLI só entrega o token de acesso (az account get-access-token); as chamadas são feitas direto.
Nada é criado, alterado ou apagado no Azure.

Referências oficiais:
  https://learn.microsoft.com/rest/api/logic/workflows/get?view=rest-logic-2019-05-01
  https://learn.microsoft.com/rest/api/logic/workflow-runs/list?view=rest-logic-2019-05-01
  https://learn.microsoft.com/rest/api/logic/workflow-run-actions/list?view=rest-logic-2019-05-01
  https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-logic-workflows-metrics
  https://learn.microsoft.com/rest/api/monitor/metrics/list
  https://learn.microsoft.com/cli/azure/account#az-account-get-access-token

Comandos (rodar na raiz do projeto):
  python tools/azure_logicapp.py configurar --assinatura <id> --grupo <grupo> --nome <logic-app>
  python tools/azure_logicapp.py baixar        definição -> logicapps/reais/<nome>.json
  python tools/azure_logicapp.py execucoes     últimas execuções e o status de cada ação
  python tools/azure_logicapp.py metricas      execuções cobradas por dia (últimos 7 dias)
  python tools/azure_logicapp.py precos        saída da ação 'Resumo' da última execução com sucesso
  python tools/azure_logicapp.py conferir      compara o que rodou no Azure com a leitura do JSON
  python tools/azure_logicapp.py sincronizar   tudo acima, em sequência
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import logicapp_parser as lp  # noqa: E402

CONFIG = ROOT / "config" / "azure.json"
SAIDA = ROOT / "relatorios" / "azure"
REAIS = ROOT / "logicapps" / "reais"
API = "2019-05-01"
METRICAS = ["BillableActionExecutions", "BillableTriggerExecutions", "TotalBillableExecutions"]


class ErroAzure(Exception):
    pass


def utf8_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def cfg():
    if not CONFIG.exists():
        raise ErroAzure("Falta configurar. Rode: python tools/azure_logicapp.py configurar "
                        "--assinatura <id> --grupo <grupo> --nome <logic-app>")
    c = json.loads(CONFIG.read_text(encoding="utf-8"))
    c["id"] = (f"/subscriptions/{c['assinatura']}/resourceGroups/{c['grupo']}"
               f"/providers/Microsoft.Logic/workflows/{c['nome']}")
    return c


def az(*args):
    exe = shutil.which("az")  # no Windows encontra o az.cmd
    if not exe:
        raise ErroAzure("Azure CLI não encontrada. Instale (winget install --exact --id Microsoft.AzureCLI), "
                        "feche e abra o terminal e rode: az login")
    # a Azure CLI é feita em Python: estas variáveis fazem ela responder em UTF-8 também no Windows
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run([exe, *args, "--output", "json"], capture_output=True, env=env)
    r.stdout, r.stderr = texto(r.stdout), texto(r.stderr)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        if "az login" in msg or "AADSTS" in msg or "No subscription found" in msg:
            raise ErroAzure("Azure CLI sem login válido. Rode: az login   (detalhe: " + msg.splitlines()[-1] + ")")
        raise ErroAzure(msg.splitlines()[-1] if msg else f"az terminou com código {r.returncode}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def texto(b):
    """Decodifica a saída da Azure CLI: UTF-8 e, se não der, a codificação do Windows (cp1252)."""
    if not b:
        return ""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1252", errors="replace")


ARM = os.environ.get("AZURE_ARM_URL", "https://management.azure.com")  # trocado só nos testes
_token = {}


def token():
    """Token de acesso do Azure Resource Manager, pedido à Azure CLI já logada (fica só na memória)."""
    if "v" not in _token:
        t = az("account", "get-access-token", "--resource", "https://management.azure.com/")
        _token["v"] = t["accessToken"]
    return _token["v"]


def get(caminho):
    """GET no Azure Resource Manager (direto, com o token), seguindo nextLink.
    Não passa pelo Prompt de Comando: o '&' dos endereços não quebra no Windows."""
    url = caminho if caminho.startswith("http") else f"{ARM}{caminho}"
    dados = _get_url(url)
    if isinstance(dados, dict) and "value" in dados and isinstance(dados["value"], list):
        itens = list(dados["value"])
        while dados.get("nextLink"):
            dados = _get_url(dados["nextLink"])
            itens += dados.get("value", [])
        return itens
    return dados


def _get_url(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(texto(resp.read()) or "null")
    except urllib.error.HTTPError as e:
        corpo = texto(e.read())
        try:
            msg = json.loads(corpo).get("error", {}).get("message", corpo)
        except ValueError:
            msg = corpo
        if e.code == 401:
            raise ErroAzure("Login expirado. Rode: az login") from None
        if e.code == 404:
            raise ErroAzure(f"Não encontrado (confira assinatura, grupo e nome em config/azure.json): {msg}") from None
        if e.code == 403:
            raise ErroAzure(f"Sem permissão de leitura nesse recurso: {msg}") from None
        raise ErroAzure(f"HTTP {e.code}: {msg}") from None


def salvar(nome, dados):
    SAIDA.mkdir(parents=True, exist_ok=True)
    p = SAIDA / nome
    p.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ------------------------------------------------------------------ comandos
def configurar(args):
    op = dict(zip(args[::2], args[1::2], strict=False))  # número ímpar de argumentos: o último fica sem valor
    faltam = [k for k in ("--assinatura", "--grupo", "--nome") if k not in op]
    if faltam:
        print("Faltou:", ", ".join(faltam))
        return 1
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"assinatura": op["--assinatura"], "grupo": op["--grupo"], "nome": op["--nome"]},
                                 indent=2), encoding="utf-8")
    print(f"Configuração salva em {CONFIG.relative_to(ROOT)} (fica fora do Git).")
    return 0


def baixar():
    c = cfg()
    wf = get(f"{c['id']}?api-version={API}")
    props = wf.get("properties", {})
    definicao = props.get("definition") or {}
    # parâmetros da Logic App podem ter valores sensíveis: guardamos só a definição
    REAIS.mkdir(parents=True, exist_ok=True)
    destino = REAIS / f"{c['nome']}.json"
    destino.write_text(json.dumps({"definition": definicao, "parameters": {}}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    info = lp.ler(definicao)
    print(f"Definição baixada: {destino.relative_to(ROOT)}")
    print(f"  estado no Azure: {props.get('state')} | versão: {props.get('version')} | "
          f"alterada em: {props.get('changedTime')}")
    print(f"  {len(info['acoes'])} ações lidas; gatilho: {info['gatilho']['texto'] if info['gatilho'] else '-'}")
    return 0


def execucoes(quantas=5):
    c = cfg()
    runs = get(f"{c['id']}/runs?api-version={API}&$top={quantas}")[:quantas]
    out = []
    for r in runs:
        p = r.get("properties", {})
        acoes = get(f"{c['id']}/runs/{r['name']}/actions?api-version={API}")
        out.append({"execucao": r["name"], "status": p.get("status"), "inicio": p.get("startTime"),
                    "fim": p.get("endTime"),
                    "acoes": {a["name"]: a.get("properties", {}).get("status") for a in acoes}})
    salvar(f"{c['nome']}-execucoes.json", out)
    if not out:
        print("Nenhuma execução ainda. No portal: abra a Logic App > Designer > Executar (ou Visão geral > Executar gatilho).")
    for e in out:
        print(f"- {e['inicio']} | {e['status']:<9} | {len(e['acoes'])} ações "
              f"({sum(1 for s in e['acoes'].values() if s == 'Skipped')} puladas)")
    return out


def metricas(dias=7):
    c = cfg()
    fim = datetime.now(timezone.utc).replace(microsecond=0)
    ini = fim - timedelta(days=dias)
    # Azure Monitor - Metrics List (REST): agregação Total por dia
    m = get(f"{c['id']}/providers/Microsoft.Insights/metrics?api-version=2018-01-01"
            f"&metricnames={','.join(METRICAS)}&aggregation=Total&interval=P1D"
            f"&timespan={ini.strftime('%Y-%m-%dT%H:%M:%SZ')}/{fim.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    m = {"value": m} if isinstance(m, list) else m
    tot = {}
    for serie in m.get("value", []):
        nome = serie["name"]["value"]
        tot[nome] = sum((d.get("total") or 0) for ts in serie.get("timeseries", []) for d in ts.get("data", []))
    salvar(f"{c['nome']}-metricas.json", {"de": ini.isoformat(), "ate": fim.isoformat(), "totais": tot, "bruto": m})
    print(f"Execuções cobradas nos últimos {dias} dias:")
    for k in METRICAS:
        print(f"  {k}: {tot.get(k, 0):.0f}")
    return tot


def precos():
    c = cfg()
    runs = get(f"{c['id']}/runs?api-version={API}&$top=20")
    ok = next((r for r in runs if r.get("properties", {}).get("status") == "Succeeded"), None)
    if not ok:
        print("Nenhuma execução com sucesso ainda.")
        return None
    acao = get(f"{c['id']}/runs/{ok['name']}/actions/Resumo?api-version={API}")
    link = ((acao or {}).get("properties", {}).get("outputsLink") or {}).get("uri")
    if not link:
        print("A ação 'Resumo' não tem saída nessa execução (o ramo 'Sim' foi pulado?).")
        return None
    try:  # link temporário (SAS) devolvido pela própria API: não leva o token
        with urllib.request.urlopen(link, timeout=30) as resp:
            saida = json.loads(texto(resp.read()))
    except (urllib.error.URLError, ValueError) as e:
        raise ErroAzure(f"Não consegui baixar a saída da ação 'Resumo': {e}") from e
    corpo = saida.get("body", saida)
    p = salvar("precos_logicapps.json", {"execucao": ok["name"], **corpo})
    print(f"Preços salvos em {p.relative_to(ROOT)}: {len(corpo.get('precos', []))} medidores "
          f"({corpo.get('regiao')}, {corpo.get('moeda')}, consultado em {corpo.get('consultado_em')})")
    return corpo


def conferir():
    """Compara o que rodou no Azure com o que o leitor entendeu do JSON."""
    c = cfg()
    arq = REAIS / f"{c['nome']}.json"
    if not arq.exists():
        baixar()
    info = lp.ler(json.loads(arq.read_text(encoding="utf-8")))
    nomes = {x["nome"] for x in info["acoes"]}
    ex = json.loads((SAIDA / f"{c['nome']}-execucoes.json").read_text(encoding="utf-8")) \
        if (SAIDA / f"{c['nome']}-execucoes.json").exists() else execucoes()
    problemas, linhas = [], []
    for e in ex:
        rodou = set(e["acoes"])
        for n in sorted(rodou - nomes):
            problemas.append(f"{e['execucao']}: o Azure executou '{n}', que o leitor não encontrou no JSON")
        for n in sorted(nomes - rodou):
            problemas.append(f"{e['execucao']}: o leitor achou '{n}', que não aparece na execução do Azure")
        # ramos de condição: no máximo um ramo pode ter rodado
        for x in info["acoes"]:
            if x["tipo"] == "If" and e["acoes"].get(x["nome"]) == "Succeeded":
                rodaram = {y["ramo"] for y in info["acoes"] if y["pai"] == x["nome"]
                           and e["acoes"].get(y["nome"]) not in (None, "Skipped")}
                if len(rodaram) > 1:
                    problemas.append(f"{e['execucao']}: os dois ramos de '{x['nome']}' rodaram")
        linhas.append(f"- {e['inicio']} | {e['status']} | ações que rodaram: "
                      f"{sum(1 for s in e['acoes'].values() if s != 'Skipped')}/{len(e['acoes'])}")
    cob = info["cobranca"]
    estimativa = f"{cob['fixas_por_execucao']} fixas" + "".join(
        f" + {v} por item de {k}" for k, v in cob["por_item_de_loop"].items())
    pre = SAIDA / "precos_logicapps.json"
    n_itens = len(json.loads(pre.read_text(encoding="utf-8")).get("precos", [])) if pre.exists() else None
    por_exec = cob["fixas_por_execucao"] + (sum(cob["por_item_de_loop"].values()) * n_itens if n_itens is not None else 0)
    met = SAIDA / f"{c['nome']}-metricas.json"
    medido = json.loads(met.read_text(encoding="utf-8"))["totais"] if met.exists() else {}
    ok_runs = [e for e in ex if e["status"] == "Succeeded"]
    print("Conferência: Azure × leitura do JSON")
    print("\n".join(linhas))
    print(f"Estimativa do leitor por execução: {estimativa}"
          + (f" = {por_exec} ações (com {n_itens} itens no loop)" if n_itens is not None else ""))
    if medido:
        print(f"Medido pelo Azure (últimos 7 dias): {medido.get('BillableActionExecutions', 0):.0f} ações cobradas, "
              f"{medido.get('BillableTriggerExecutions', 0):.0f} disparos de gatilho")
        disparos = medido.get("BillableTriggerExecutions", 0)
        if n_itens is not None and disparos and len(ok_runs) == len(ex):
            # cada disparo do gatilho = uma execução; ações cobradas ÷ disparos = ações por execução
            real = medido.get("BillableActionExecutions", 0) / disparos
            print(f"Por execução: medido {real:g} ações × previsto {por_exec} → "
                  + ("BATE" if abs(real - por_exec) < 0.01 else "NÃO BATE"))
            if abs(real - por_exec) >= 0.01:
                problemas.append(f"custo: o Azure cobrou {real:g} ações por execução e o leitor previu {por_exec}")
            if disparos < len(ex):
                print(f"  (as métricas ainda contam {disparos:.0f} de {len(ex)} execuções listadas: "
                      "o Azure leva alguns minutos para atualizar)")
    for p in problemas:
        print("PROBLEMA   ", p)
    if not ex:
        print("\nRESULTADO: SEM EXECUÇÕES PARA CONFERIR (rode a Logic App uma vez e sincronize de novo)")
        return 0
    print("\nRESULTADO:", "AZURE E LEITURA BATEM" if not problemas else f"DIVERGÊNCIAS ({len(problemas)})")
    return 0 if not problemas else 1


def main(argv):
    utf8_stdout()
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "configurar":
            return configurar(argv[2:])
        if cmd == "baixar":
            return baixar()
        if cmd == "execucoes":
            execucoes()
        elif cmd == "metricas":
            metricas()
        elif cmd == "precos":
            precos()
        elif cmd == "conferir":
            return conferir()
        elif cmd == "sincronizar":
            for etapa in (baixar, execucoes, metricas, precos):
                print(f"\n== {etapa.__name__} ==")
                etapa()
            print("\n== conferir ==")
            return conferir()
        else:
            print(__doc__)
            return 1
    except ErroAzure as e:
        print("ERRO:", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
