"""Catálogo de automações: todas as Logic Apps num lugar só, com o que cada uma faz e como está rodando.

Junta duas fontes, sem IA:
  - a definição JSON de cada Logic App (tools/logicapp_parser.py): gatilho, conectores, chamadas a outras
    Logic Apps, tratamento de erro, achados de boas práticas e ações cobradas;
  - os dados de operação: estado, tags, execuções por dia, últimas execuções e status das conexões.
    Exemplos fictícios: logicapps/operacao/exemplos.json. Logic App real: relatorios/azure/<nome>-operacao.json,
    gravado por `python tools/azure_logicapp.py operacao` (só leitura).

Sinais de operação (além dos achados da definição):
  CONEXAO_COM_ERRO  (Alta)  uma conexão usada pela Logic App está com status de erro no Azure
  FALHANDO          (Alta)  10% ou mais das execuções dos últimos 30 dias falharam
  PARADA            (Alta)  habilitada, com agenda, e sem rodar há mais de 2 intervalos (mínimo 2 dias)
  FALHAS_PONTUAIS   (Média) falhou alguma vez nos últimos 30 dias, abaixo de 10%
  SEM_DONO          (Média) sem a tag owner: ninguém para chamar quando quebrar
  DESABILITADA      (Baixa) desligada no Azure: confirmar se é intencional
Situação: Crítico (algum sinal ou achado Alta), Atenção (Média ou Baixa), OK (nada) ou Sem dados (sem operação).

Comandos (na raiz do projeto):
  python tools/catalogo_logicapps.py            resumo no terminal
  python tools/catalogo_logicapps.py gerar      docs/logicapps/CATALOGO.md + relatorios/catalogo_logicapps.json
  python tools/catalogo_logicapps.py json       o catálogo em JSON (usado pelo hub)

Referências oficiais:
  https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-logic-workflows-metrics
  https://learn.microsoft.com/azure/templates/microsoft.web/connections
  https://learn.microsoft.com/azure/logic-apps/logic-apps-workflow-actions-triggers#workflow-action
"""
import json
import os
import sys
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doc_logicapp as dl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OPERACAO_EXEMPLOS = Path(os.environ.get("CATALOGO_OPERACAO") or ROOT / "logicapps" / "operacao" / "exemplos.json")
OPERACAO_REAL = ROOT / "relatorios" / "azure"
SAIDA_MD = ROOT / "docs" / "logicapps" / "CATALOGO.md"
SAIDA_JSON = ROOT / "relatorios" / "catalogo_logicapps.json"

LIMITE_FALHA = Fraction(10, 100)
SINAIS = {
    "CONEXAO_COM_ERRO": ("Alta", "Uma conexão usada por esta Logic App está com erro no Azure.",
                         "Reautorizar a conexão (API connections > Edit API connection > Authorize) com a conta certa."),
    "FALHANDO": ("Alta", "10% ou mais das execuções dos últimos 30 dias falharam.",
                 "Abrir a execução com falha no histórico, ver a ação em vermelho e corrigir a causa; depois reenviar."),
    "PARADA": ("Alta", "Está habilitada e tem agenda, mas não roda há mais de 2 intervalos.",
               "Conferir o histórico de gatilhos e se a assinatura e as conexões estão ativas."),
    "FALHAS_PONTUAIS": ("Média", "Falhou alguma vez nos últimos 30 dias (menos de 10% das execuções).",
                        "Ver se a falha é passageira (408/429/5xx) e se a ação tem política de retentativa."),
    "SEM_DONO": ("Média", "Sem a tag owner: ninguém é avisado quando quebrar.",
                 "Adicionar a tag owner com o time responsável."),
    "DESABILITADA": ("Baixa", "Desligada no Azure.", "Confirmar se é intencional; se não for mais usada, registrar e remover."),
}
ORDEM_SIT = {"Crítico": 0, "Atenção": 1, "OK": 2, "Sem dados": 3}


def utf8_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _ler(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def operacoes():
    """Dados de operação por Logic App: {nome: {...}} e conexões por id. A real (sincronizada) vale mais que o exemplo."""
    base = _ler(OPERACAO_EXEMPLOS) or {}
    ref = base.get("data_referencia")
    las = {n: {**v, "origem": "exemplo fictício", "data_referencia": ref, "dias": base.get("dias", 30)}
           for n, v in (base.get("logicapps") or {}).items()}
    conexoes = dict(base.get("conexoes") or {})
    for arq in sorted(OPERACAO_REAL.glob("*-operacao.json")) if OPERACAO_REAL.exists() else []:
        d = _ler(arq)
        if not d or "nome" not in d:
            continue
        las[d["nome"]] = {**d, "origem": "medido no Azure"}
        conexoes.update(d.get("conexoes") or {})
    return las, conexoes


def _id_nome(rid):
    return (rid or "").rstrip("/").rsplit("/", 1)[-1]


def _ids_conexoes(nome):
    """Ids dos recursos de conexão (Microsoft.Web/connections) que a Logic App usa, lidos do $connections do arquivo."""
    _, params, _ = dl.carregar(nome)
    val = ((params or {}).get("$connections") or {}).get("value") or {}
    return {k: v.get("connectionId") for k, v in val.items() if isinstance(v, dict)}


def dependencias(infos):
    """Quem chama quem: ação Workflow (Logic App filha) e HTTP para endpoint de Logic App."""
    chama = {}
    for i in infos:
        alvos = []
        for x in i["acoes"]:
            if x["tipo"] == "Workflow":
                alvos.append({"nome": _id_nome(x["detalhes"].get("fluxo_filho")), "por": x["nome"], "como": "ação Workflow"})
            elif x["tipo"] in ("Http", "HttpWebhook"):
                uri = ((x["acao"].get("inputs") or {}).get("uri") or "") if isinstance(x["acao"].get("inputs"), dict) else ""
                if ".logic.azure.com" in uri:
                    alvos.append({"nome": None, "por": x["nome"], "como": "HTTP para o endereço de outra Logic App"})
        chama[i["nome"]] = alvos
    chamada_por = {i["nome"]: [] for i in infos}
    for origem, alvos in chama.items():
        for a in alvos:
            if a["nome"] in chamada_por and origem not in chamada_por[a["nome"]]:
                chamada_por[a["nome"]].append(origem)
    return chama, chamada_por


def _pct(f):
    return round(float(f) * 100, 1)


def montar():
    infos = [dl.analisar(n) for n in dl.nomes()]
    ops, conexoes = operacoes()
    chama, chamada_por = dependencias(infos)
    itens, uso_conexoes = [], {}
    for i in infos:
        n, g = i["nome"], i["gatilho"]
        ag = (g or {}).get("agenda")
        op = ops.get(n)
        ids = _ids_conexoes(n) or dict((op or {}).get("conexoes_por_chave") or {})
        for rid in ids.values():
            uso_conexoes.setdefault(rid, []).append(n)
        conns = []
        for chave, rid in sorted(ids.items()):
            c = conexoes.get(rid) or {}
            conns.append({"chave": chave, "id": rid, "api": c.get("api") or chave, "nome": dl.con_pt(c.get("api") or chave),
                          "status": c.get("status") or "desconhecido", "erro": c.get("erro"),
                          "compartilhada_com": []})
        item = {"nome": n, "ficticio": i.get("ficticio", False), "arquivo": i["arquivo"],
                "doc": f"docs/logicapps/{n}.md", "gatilho": g["texto"] if g else "-",
                "sob_demanda": bool(g and g["tipo"] in ("Request", "ApiConnectionWebhook", "HttpWebhook")),
                "acoes": len(i["acoes"]), "trata_erro": i["trata_erro"],
                "conectores": [dl.con_pt(c) for c in i["conectores"]], "conexoes": conns,
                "chama": chama.get(n, []), "chamada_por": chamada_por.get(n, []),
                "achados": [{"regra": r, "severidade": dl.lp.REGRAS[r][0], "onde": o} for r, o, _ in i["achados"]],
                "execucoes_previstas_30d": None, "acoes_por_execucao": i["cobranca"]["fixas_por_execucao"],
                "custo_previsto_mes": None, "operacao": None, "sinais": []}
        if ag and ag.get("por_dia") is not None:
            item["execucoes_previstas_30d"] = float(Fraction(ag["por_dia"]) * 30)
        cm = dl.custo_mes(i)
        if cm and "erro" not in cm:
            item["custo_previsto_mes"] = {"valor": round(cm["custo"], 2), "moeda": cm["moeda"]}
        if op:
            item["operacao"] = _operacao(op, ag)
            item["dono"] = (op.get("tags") or {}).get("owner")
            item["estado"] = op.get("estado")
            item["origem_operacao"] = op.get("origem")
        else:
            item["dono"], item["estado"], item["origem_operacao"] = None, None, None
        item["sinais"] = _sinais(item, op, i)
        item["situacao"] = _situacao(item)
        itens.append(item)
    # conexões compartilhadas: quem cai junto se uma conexão quebrar
    for it in itens:
        for c in it["conexoes"]:
            c["compartilhada_com"] = sorted(x for x in uso_conexoes.get(c["id"], []) if x != it["nome"])
    lista_conexoes = []
    for rid, usam in sorted(uso_conexoes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        c = conexoes.get(rid) or {}
        lista_conexoes.append({"id": rid, "recurso": _id_nome(rid), "api": c.get("api"), "nome": dl.con_pt(c.get("api") or _id_nome(rid)),
                               "nome_exibicao": c.get("nome_exibicao"), "status": c.get("status") or "desconhecido",
                               "erro": c.get("erro"), "usada_por": sorted(usam)})
    # impacto: se uma Logic App chamada por outras estiver em situação crítica, quem a chama herda o risco
    for it in itens:
        it["afeta"] = sorted(chamada_por.get(it["nome"], []))
    itens.sort(key=lambda x: (ORDEM_SIT[x["situacao"]], x["nome"]))
    resumo = {s: sum(1 for x in itens if x["situacao"] == s) for s in ORDEM_SIT}
    ref = next((op.get("data_referencia") for op in ops.values() if op.get("data_referencia")), None)
    return {"gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"), "data_referencia": ref,
            "total": len(itens), "por_situacao": resumo, "logicapps": itens, "conexoes": lista_conexoes,
            "dependencias": _agrupa_dependencias(chama)}


def _agrupa_dependencias(chama):
    """Uma linha por par (quem chama → quem é chamada), com as ações que fazem a chamada."""
    out = {}
    for origem, alvos in chama.items():
        for a in alvos:
            d = out.setdefault((origem, a["nome"]), {"de": origem, "para": a["nome"], "por": [], "como": a["como"]})
            d["por"].append(a["por"])
    return list(out.values())


def _operacao(op, ag):
    dias = op.get("execucoes_por_dia") or {}
    ok = sum(int(v.get("Succeeded", 0)) for v in dias.values())
    falhas = sum(int(v.get("Failed", 0)) for v in dias.values())
    total = ok + falhas
    ref = date.fromisoformat(op.get("data_referencia") or max(dias, default=date.today().isoformat()))
    datas_com_execucao = sorted(d for d, v in dias.items() if sum(int(x) for x in v.values()) > 0)
    ultimas = sorted(op.get("ultimas_execucoes") or [], key=lambda e: e.get("inicio") or "", reverse=True)
    ultima = ultimas[0] if ultimas else None
    ultima_data = (ultima or {}).get("inicio", "")[:10] or (datas_com_execucao[-1] if datas_com_execucao else None)
    ultima_falha = next((e for e in ultimas if e.get("status") == "Failed"), None)
    return {"execucoes_30d": total, "sucesso_30d": ok, "falhas_30d": falhas,
            "taxa_falha_pct": _pct(Fraction(falhas, total)) if total else 0.0,
            "_taxa": Fraction(falhas, total) if total else Fraction(0),
            "ultima_execucao": ultima_data, "ultimo_status": (ultima or {}).get("status"),
            "ultima_falha": ultima_falha, "dias_sem_rodar": (ref - date.fromisoformat(ultima_data)).days if ultima_data else None,
            "data_referencia": ref.isoformat(),
            "primeira_falha_no_periodo": next((d for d in sorted(dias) if int(dias[d].get("Failed", 0)) > 0), None)}


TRANSITORIOS = {"ServiceUnavailable", "TooManyRequests", "RequestTimeout", "GatewayTimeout", "BadGateway",
                "InternalServerError", "408", "429", "500", "502", "503", "504"}


def causa_provavel(item, info):
    """Liga a última falha à definição: a ação que falhou usa uma conexão com erro? É erro passageiro numa ação
    sem retentativa? Devolve o texto ou None (sem palpite quando os dados não sustentam)."""
    f = (item["operacao"] or {}).get("ultima_falha")
    if not f or not f.get("acao_com_falha"):
        return None
    acao = next((x for x in info["acoes"] if x["nome"] == f["acao_com_falha"]), None)
    if not acao:
        return None
    con = next((c for c in item["conexoes"] if c["chave"] == acao["conector"] or c["api"] == acao["conector"]), None)
    if con and con["status"] not in ("Connected", "desconhecido"):
        return f"a ação `{acao['nome']}` usa a conexão {con['nome']}, que está com erro ({f.get('codigo') or con['status']})"
    if str(f.get("codigo")) in TRANSITORIOS and acao["retentativa"]["tipo"] == "none":
        return (f"a ação `{acao['nome']}` falhou com {f['codigo']} (erro passageiro) e está sem retentativa: "
                "com a política padrão o Azure teria tentado de novo")
    return f"a última falha foi na ação `{acao['nome']}` ({f.get('codigo') or 'sem código'})"


def _sinais(item, op, info):
    s = []
    if not op:
        return s
    o = item["operacao"]
    if any(c["status"] not in ("Connected", "desconhecido") for c in item["conexoes"]):
        s.append({"sinal": "CONEXAO_COM_ERRO", "detalhe": ", ".join(
            f"{c['nome']} ({c['status']}{': ' + c['erro']['codigo'] if c.get('erro') else ''}"
            f"{' desde ' + _data(c['erro']['desde']) if c.get('erro') and c['erro'].get('desde') else ''})"
            for c in item["conexoes"] if c["status"] not in ("Connected", "desconhecido"))})
    if o["falhas_30d"] and o["_taxa"] >= LIMITE_FALHA:
        s.append({"sinal": "FALHANDO", "detalhe": f"{_br_num(o['falhas_30d'])} de {_br_num(o['execucoes_30d'])} execuções ({_pct_br(o)})"
                  + (f", desde {_data(o['primeira_falha_no_periodo'])}" if o.get("primeira_falha_no_periodo") else "")
                  + (f". Causa provável: {c}" if (c := causa_provavel(item, info)) else "")})
    elif o["falhas_30d"]:
        s.append({"sinal": "FALHAS_PONTUAIS",
                  "detalhe": f"{_br_num(o['falhas_30d'])} de {_br_num(o['execucoes_30d'])} execuções ({_pct_br(o)})"
                  + (f". Causa provável: {c}" if (c := causa_provavel(item, info)) else "")})
    if item["estado"] == "Disabled":
        s.append({"sinal": "DESABILITADA", "detalhe": "estado Disabled no Azure"})
    elif item["execucoes_previstas_30d"] and not item["sob_demanda"]:
        intervalo_dias = 30 / item["execucoes_previstas_30d"]  # dias entre execuções
        limite = max(2, 2 * intervalo_dias)
        if o["dias_sem_rodar"] is None or o["dias_sem_rodar"] > limite:
            s.append({"sinal": "PARADA", "detalhe": ("nenhuma execução registrada" if o["dias_sem_rodar"] is None else
                      f"última execução há {o['dias_sem_rodar']} dias (esperado a cada {round(intervalo_dias, 2):g} dia(s))")})
    if not item["dono"]:
        s.append({"sinal": "SEM_DONO", "detalhe": "tag owner ausente"})
    for x in s:
        x["severidade"], x["descricao"], x["recomendacao"] = SINAIS[x["sinal"]]
    return s


def _situacao(item):
    if item["operacao"] is None:
        return "Sem dados"
    sevs = [x["severidade"] for x in item["sinais"]] + [a["severidade"] for a in item["achados"]]
    if "Alta" in sevs:
        return "Crítico"
    return "Atenção" if sevs else "OK"


def publico(cat):
    """Versão para JSON (sem frações internas)."""
    out = json.loads(json.dumps(cat, default=str))
    for it in out["logicapps"]:
        if it["operacao"]:
            it["operacao"].pop("_taxa", None)
    return out


# ------------------------------------------------------------------ texto
def _br_num(v):
    if v is None:
        return "-"
    return f"{v:,.0f}".replace(",", ".") if float(v).is_integer() else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct_br(o):
    return f"{o['taxa_falha_pct']:.1f}%".replace(".", ",")


def _data(d):
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}" if d else "-"


def markdown(cat):
    ps = cat["por_situacao"]
    L = ["---", "type: moc", "tags: [documentacao, logic-apps, catalogo, gerado-automaticamente]", "area: projetos", "---",
         "# Catálogo de automações",
         f"> Gerado em {datetime.now():%d/%m/%Y %H:%M} por código (`tools/catalogo_logicapps.py`). Operação dos últimos 30 dias "
         f"até {_data(cat['data_referencia'])}. Logic Apps de exemplo e seus dados de operação são fictícios.", "",
         f"**{cat['total']} Logic Apps:** {ps['Crítico']} crítica(s), {ps['Atenção']} com atenção, {ps['OK']} ok"
         + (f", {ps['Sem dados']} sem dados de operação" if ps["Sem dados"] else "") + ".", "",
         "| Situação | Logic App | Dono | Quando roda | Execuções 30d | Falhas | Última execução | Conexões | Trata erro |",
         "|---|---|---|---|---|---|---|---|---|"]
    for it in cat["logicapps"]:
        o = it["operacao"] or {}
        conns = ", ".join(f"{c['nome']}{'' if c['status'] in ('Connected', 'desconhecido') else ' ⚠️ ' + c['status']}"
                          for c in it["conexoes"]) or "-"
        dono = (it["dono"] or "**sem dono**") if o else "-"
        L.append(f"| {it['situacao']} | [[{it['nome']}]]{' (exemplo)' if it['ficticio'] else ''} | {dono} | "
                 f"{it['gatilho']} | {_br_num(o.get('execucoes_30d'))} | "
                 + (f"{_br_num(o['falhas_30d'])} ({_pct_br(o)})" if o else "-")
                 + f" | {_data(o.get('ultima_execucao'))} {('(' + o['ultimo_status'] + ')') if o.get('ultimo_status') else ''} | "
                 f"{conns} | {'sim' if it['trata_erro'] else 'não'} |")
    L += ["", "## O que precisa de ação"]
    acao = [it for it in cat["logicapps"] if it["situacao"] in ("Crítico", "Atenção")]
    if not acao:
        L.append("Nada: todas as Logic Apps com dados estão ok.")
    for it in acao:
        L.append(f"### {it['nome']} — {it['situacao']}")
        for s in it["sinais"]:
            L.append(f"- **[{s['severidade']}] {s['sinal']}:** {s['descricao']} ({s['detalhe']}). *O que fazer:* {s['recomendacao']}")
        for a in it["achados"]:
            sev, _cat, desc, rec = dl.lp.REGRAS[a["regra"]]
            L.append(f"- **[{sev}] {a['regra']}** em `{a['onde']}`: {desc} *O que fazer:* {rec}")
        if it["afeta"]:
            L.append(f"- **Impacto:** é chamada por {', '.join(f'[[{x}]]' for x in it['afeta'])}; se parar, elas também falham.")
        L.append("")
    L += ["## Conexões", "Uma conexão com erro derruba todas as Logic Apps que a usam.", "",
          "| Conexão | Serviço | Status | Usada por |", "|---|---|---|---|"]
    for c in cat["conexoes"]:
        st = c["status"] + (f" ({c['erro']['codigo']} desde {_data(c['erro'].get('desde'))})" if c.get("erro") else "")
        L.append(f"| {c['recurso']}{' — ' + c['nome_exibicao'] if c.get('nome_exibicao') else ''} | {c['nome']} | {st} | "
                 f"{', '.join(f'[[{u}]]' for u in c['usada_por'])} |")
    L += ["", "## Quem chama quem"]
    if cat["dependencias"]:
        L += ["```mermaid", "flowchart LR"]
        for d in cat["dependencias"]:
            L.append(f"    {d['de'].replace('-', '_')}[\"{d['de']}\"] -->|{' / '.join(d['por'])}| "
                     f"{(d['para'] or 'desconhecida').replace('-', '_')}[\"{d['para'] or 'Logic App não identificada'}\"]")
        L.append("```")
    else:
        L.append("Nenhuma Logic App chama outra.")
    L += ["", "## Como ler", "- **Crítico:** conexão com erro, 10% ou mais de falhas, parada, ou achado de severidade alta na definição.",
          "- **Atenção:** sem dono, falhas pontuais, desabilitada, ou achado médio/baixo.",
          "- **Sem dados:** a definição foi lida, mas falta a operação (rode `python tools/azure_logicapp.py sincronizar`).",
          "- Execuções e falhas vêm das métricas RunsSucceeded e RunsFailed do Azure Monitor; conexões, do recurso "
          "Microsoft.Web/connections. Nada é alterado no Azure.", "", "---", "↩︎ [[INDICE Logic Apps]]"]
    return "\n".join(L) + "\n"


def texto(cat):
    ps = cat["por_situacao"]
    L = [f"Catálogo de automações: {cat['total']} Logic Apps ({ps['Crítico']} crítica(s), {ps['Atenção']} com atenção, "
         f"{ps['OK']} ok, {ps['Sem dados']} sem dados). Operação: 30 dias até {_data(cat['data_referencia'])}."]
    for it in cat["logicapps"]:
        o = it["operacao"]
        dono = (it["dono"] or "SEM DONO") if o else "-"
        L.append(f"- [{it['situacao']}] {it['nome']} | dono: {dono} | {it['gatilho']}"
                 + (f" | {_br_num(o['execucoes_30d'])} execução(ões), {_br_num(o['falhas_30d'])} falha(s) ({_pct_br(o)}), "
                    f"última {_data(o['ultima_execucao'])} ({o['ultimo_status']})" if o else " | sem dados de operação"))
        for s in it["sinais"]:
            L.append(f"    {s['sinal']} ({s['severidade']}): {s['detalhe']}")
        if it["chama"]:
            L.append("    chama: " + ", ".join(f"{d['para'] or 'Logic App não identificada'} (por {', '.join(d['por'])})"
                                         for d in _agrupa_dependencias({it['nome']: it['chama']})))
        if it["chamada_por"]:
            L.append("    chamada por: " + ", ".join(it["chamada_por"]))
    L.append("Conexões:")
    for c in cat["conexoes"]:
        L.append(f"- {c['recurso']} ({c['nome']}): {c['status']}"
                 + (f" ({c['erro']['codigo']} desde {_data(c['erro'].get('desde'))})" if c.get("erro") else "")
                 + f" | usada por {len(c['usada_por'])}: {', '.join(c['usada_por'])}")
    return "\n".join(L)


def gerar():
    cat = montar()
    SAIDA_MD.parent.mkdir(parents=True, exist_ok=True)
    SAIDA_MD.write_text(markdown(cat), encoding="utf-8")
    SAIDA_JSON.parent.mkdir(parents=True, exist_ok=True)
    SAIDA_JSON.write_text(json.dumps(publico(cat), ensure_ascii=False, indent=1), encoding="utf-8")
    print(texto(cat))
    print(f"\nGerado: {SAIDA_MD.relative_to(ROOT).as_posix()} e {SAIDA_JSON.relative_to(ROOT).as_posix()}")
    return 0


def main(argv):
    utf8_stdout()
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "gerar":
        return gerar()
    if cmd == "json":
        print(json.dumps(publico(montar()), ensure_ascii=False, indent=1))
        return 0
    if cmd in ("", "resumo"):
        print(texto(montar()))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
