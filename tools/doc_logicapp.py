"""Documentação automática de Logic Apps a partir da definição JSON (Workflow Definition Language).

A leitura do JSON fica em tools/logicapp_parser.py (determinística e testada).
Este arquivo só transforma a leitura em texto: resumo para o agente e página Markdown para o Obsidian.

Comandos:
  python tools/doc_logicapp.py listar
  python tools/doc_logicapp.py resumo [nome]        (nome também pode vir da variável de ambiente 'nome')
  python tools/doc_logicapp.py achados
  python tools/doc_logicapp.py gerar                (gera docs/logicapps/*.md + índice e valida)
  python tools/doc_logicapp.py gerar --hook         (modo hook: saída curta + docs/logicapps/hook.log)

Pastas lidas: logicapps/exemplos (fictícias) e logicapps/reais (JSON exportado do portal; veja o LEIA-ME
dessa pasta). A variável de ambiente LOGICAPPS_DIR troca por uma pasta só (usada nos testes).
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import logicapp_parser as lp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PASTAS = [ROOT / os.environ["LOGICAPPS_DIR"]] if os.environ.get("LOGICAPPS_DIR") else \
    [ROOT / "logicapps" / "exemplos", ROOT / "logicapps" / "reais"]
OUT = ROOT / "docs" / "logicapps"

TIPO_PT = {"ApiConnection": "Conector gerenciado", "ApiConnectionWebhook": "Conector gerenciado (webhook)",
           "Http": "Chamada HTTP", "HttpWebhook": "HTTP webhook", "Foreach": "Loop (Para cada)",
           "Until": "Loop (Até que)", "If": "Condição", "Switch": "Switch (casos)", "Scope": "Escopo (bloco)",
           "Compose": "Compor", "ParseJson": "Analisar JSON", "Query": "Filtrar matriz", "Select": "Selecionar",
           "Join": "Unir", "Table": "Tabela HTML/CSV", "Response": "Resposta HTTP", "Terminate": "Encerrar",
           "Wait": "Aguardar", "Workflow": "Chamar outro fluxo", "Function": "Azure Function",
           "JavaScriptCode": "Código JavaScript", "InitializeVariable": "Inicializar variável",
           "SetVariable": "Definir variável", "IncrementVariable": "Incrementar variável",
           "DecrementVariable": "Decrementar variável", "AppendToArrayVariable": "Acrescentar à matriz",
           "AppendToStringVariable": "Acrescentar ao texto", "Recurrence": "Recorrência",
           "Request": "Requisição HTTP (manual)"}
CONECTOR_PT = {"sharepointonline": "SharePoint", "office365": "Office 365 Outlook",
               "excelonlinebusiness": "Excel Online (Business)", "azureblob": "Azure Blob Storage",
               "teams": "Microsoft Teams", "sql": "SQL Server", "onedriveforbusiness": "OneDrive for Business",
               "servicebus": "Azure Service Bus", "keyvault": "Azure Key Vault", "outlook": "Outlook.com",
               "azuremonitorlogs": "Azure Monitor Logs", "approvals": "Aprovações"}
STATUS_PT = {"Succeeded": "terminar com sucesso", "Failed": "falhar", "Skipped": "for pulada",
             "TimedOut": "esgotar o tempo"}
RETRY_PT = {"none": "desligada (none)", "fixed": "intervalo fixo", "exponential": "intervalo exponencial"}
UNID_WAIT = {"Second": "segundo(s)", "Minute": "minuto(s)", "Hour": "hora(s)", "Day": "dia(s)",
             "Week": "semana(s)", "Month": "mês(es)"}


def utf8_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def arquivos():
    out = {}
    for pasta in PASTAS:
        for p in sorted(pasta.glob("*.json")):
            out.setdefault(p.stem, p)  # nome repetido: vale o da primeira pasta
    return out


def nomes():
    return sorted(arquivos())


def carregar(nome):
    p = arquivos()[nome]
    d = json.loads(p.read_text(encoding="utf-8-sig"))  # utf-8-sig: aceita o arquivo salvo pelo Bloco de Notas
    return d.get("definition", d), d.get("parameters", {}), p


def analisar(nome):
    d, _, p = carregar(nome)
    info = lp.ler(d)
    info["nome"], info["arquivo"] = nome, p.relative_to(ROOT).as_posix()
    info["ficticio"] = p.parent.name == "exemplos"
    return info


# ---------------------------------------------------------------- textos
def con_pt(c):
    return CONECTOR_PT.get(c, c) if c else ""


def num(f):
    return lp._num(f)


def mascara(texto):
    """Esconde valores de chaves em URLs e cabeçalhos (a doc não pode repetir segredo)."""
    if not isinstance(texto, str) or "?" not in texto:
        return texto
    base, q = texto.split("?", 1)
    partes = []
    for par in q.split("&"):
        k, sep, v = par.partition("=")
        partes.append(f"{k}=***" if k.strip().lower() in ("code", "sig", "key", "api-key", "apikey") and v else par)
    return base + "?" + "&".join(partes)


def curto(v, n=140):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    s = s.replace("\n", " ").replace("|", "\\|")
    return s if len(s) <= n else s[:n - 1] + "…"


def ref_pt(r, proprio):
    tipo, _, alvo = r.partition(":")
    if tipo == "acao":
        return f"saída de `{alvo}`"
    if tipo == "gatilho":
        return "dados recebidos pelo gatilho"
    if tipo == "variavel":
        return f"variável `{alvo}`"
    if tipo == "parametro":
        return f"parâmetro `{alvo}`"
    if tipo == "item":
        if alvo == proprio:
            return "cada item da própria lista"
        return "item atual (fora de loop: erro)" if alvo == "?" else f"item atual do loop `{alvo}`"
    return r


def o_que_faz(x):
    t, d = x["tipo"], x["detalhes"]
    if t in lp.CONECTOR_TIPOS:
        s = f"Usa o conector **{con_pt(x['conector'])}** para: {d['operacao']}."
        body = (x["acao"].get("inputs") or {}).get("body")
        if isinstance(body, dict) and "Subject" in body:
            s += f" Para: `{curto(body.get('To', '-'), 80)}`; assunto: “{curto(body.get('Subject'), 80)}”."
        return s
    if t == "Http":
        q = "; ".join(f"{k} = `{curto(v, 90)}`" for k, v in d["consulta"].items())
        return f"Faz uma chamada HTTP **{d['metodo']}** para `{curto(mascara(d['uri']), 120)}`" + \
            (f" com os parâmetros: {q}." if q else ".")
    if t == "Foreach":
        modo = "um item por vez (sequencial)" if d["sequencial"] else (
            f"até {d['paralelismo']} itens ao mesmo tempo" if d["paralelismo"] else "vários itens ao mesmo tempo (paralelo)")
        return f"Repete as ações de dentro para cada item de `{curto(d['sobre'], 90)}`, {modo}."
    if t == "Until":
        lim = " ou ".join(p for p in [f"{d['limite_vezes']} voltas" if d["limite_vezes"] else "",
                                       f"tempo {d['limite_tempo']}" if d["limite_tempo"] else ""] if p)
        return f"Repete as ações de dentro até que `{curto(d['condicao'], 90)}` seja verdadeira" + \
            (f"; para no máximo após {lim}." if lim else ".")
    if t == "If":
        return f"Verifica a condição `{curto(d['condicao'], 120)}`. Se verdadeira, segue o ramo **Sim**; senão, o ramo **Não**."
    if t == "Switch":
        casos = ", ".join(f"{k} = `{v}`" for k, v in d["casos"].items())
        return f"Compara `{curto(d['expressao'], 80)}` com os casos ({casos})" + \
            ("; se nenhum bater, segue o ramo **Padrão**." if d["tem_padrao"] else "; se nenhum bater, não faz nada.")
    if t == "Scope":
        return "Agrupa as ações de dentro. O resultado do bloco (sucesso ou falha) pode disparar ações seguintes."
    if t == "InitializeVariable":
        return "Cria " + "; ".join(f"a variável `{v['nome']}` ({v['tipo']}) com valor inicial `{curto(v['valor'], 60)}`"
                                   for v in d["variaveis"]) + "."
    verbos = {"SetVariable": "Troca o valor da variável `{v}` para `{val}`.",
              "IncrementVariable": "Soma `{val}` à variável `{v}`.",
              "DecrementVariable": "Subtrai `{val}` da variável `{v}`.",
              "AppendToArrayVariable": "Acrescenta `{val}` ao fim da lista na variável `{v}`.",
              "AppendToStringVariable": "Acrescenta `{val}` ao fim do texto na variável `{v}`."}
    if t in verbos:
        return verbos[t].format(v=d["variavel"], val=curto(d["valor"], 80))
    if t == "Compose":
        return f"Monta um valor a partir de: `{curto(d['entrada'], 120)}`."
    if t == "ParseJson":
        campos = ", ".join(f"{k} ({v})" for k, v in d["campos"].items()) or "nenhum campo declarado"
        return f"Lê o JSON de `{curto(d['conteudo'], 80)}` e expõe os campos: {campos}."
    if t == "Query":
        return f"Filtra a lista `{curto(d['de'], 80)}` mantendo os itens em que `{curto(d['onde'], 80)}`."
    if t == "Select":
        mapa = ", ".join(d["mapa"]) if isinstance(d["mapa"], list) else curto(d["mapa"], 60)
        return f"Transforma cada item de `{curto(d['de'], 80)}` em: {mapa}."
    if t == "Join":
        return f"Junta os itens de `{curto(d['de'], 80)}` num texto, separados por `{d['separador']}`."
    if t == "Table":
        cols = d["colunas"] if isinstance(d["colunas"], str) else ", ".join(map(str, d["colunas"]))
        return f"Cria uma tabela {d['formato']} a partir de `{curto(d['de'], 80)}` (colunas: {cols})."
    if t == "Response":
        return f"Responde à chamada HTTP que iniciou o fluxo com o status **{d['status']}**."
    if t == "Terminate":
        return f"Encerra a execução com status **{d['status']}**" + (f" e a mensagem “{d['erro']}”." if d["erro"] else ".")
    if t == "Wait":
        if d["intervalo"]:
            c, u = d["intervalo"].split(" ", 1)
            return f"Espera {c} {UNID_WAIT.get(u, u)} antes de continuar."
        return f"Espera até `{d['ate']}` antes de continuar."
    if t == "Workflow":
        return f"Chama outro fluxo (Logic App filha) `{str(d['fluxo_filho']).rstrip('/').split('/')[-1]}`."
    if t == "Function":
        return f"Chama a Azure Function `{str(d['funcao']).rstrip('/').split('/')[-1]}` ({d['metodo']})."
    if t == "JavaScriptCode":
        return (f"Executa um trecho de JavaScript ({d['linhas_de_codigo']} linha(s)). "
                "O que o código lê de outras ações não é analisado automaticamente: confira no JSON.")
    return f"Ação do tipo {t}."


def quando(x):
    if not x["run_after"]:
        if x["pai"] is None:
            return "logo no início, quando o gatilho dispara"
        return f"no início do bloco `{x['pai']}`" + (f" (ramo {x['ramo']})" if x["ramo"] else "")
    return "; ".join(f"depois que `{d}` " + " ou ".join(STATUS_PT.get(s, s) for s in st)
                     for d, st in x["run_after"].items())


def resumo_texto(i):
    g = i["gatilho"]
    ag = g.get("agenda") if g else None
    linhas = [f"Logic App: {i['nome']} (arquivo {i['arquivo']})",
              f"Gatilho: {g['nome']} ({g['tipo']}) — {g['texto']}" if g else "Gatilho: nenhum",
              f"Execuções do gatilho: {num(ag['por_dia'])}/dia, {num(ag['por_mes'])}/mês" if ag else "",
              f"Conectores: {', '.join(con_pt(c) for c in i['conectores']) or 'nenhum'}",
              f"Total de ações: {len(i['acoes'])} | tratamento de erro: {'sim' if i['trata_erro'] else 'NÃO'}",
              "Passo a passo (ordem de execução):"]
    for x in i["acoes"]:
        linhas.append(f"  {'  ' * x['nivel']}{x['numero']}. {x['nome']} ({TIPO_PT.get(x['tipo'], x['tipo'])}): {o_que_faz(x)}")
    if i["variaveis"]:
        linhas.append("Variáveis: " + ", ".join(f"{k} ({v['tipo']})" for k, v in i["variaveis"].items()))
    c = i["cobranca"]
    linhas.append(f"Ações cobradas por execução: {c['fixas_por_execucao']} fixas"
                  + "".join(f" + {v} por item de {k}" for k, v in c["por_item_de_loop"].items()))
    linhas.append(f"Achados de boas práticas: {len(i['achados'])}")
    for r, onde, det in i["achados"]:
        linhas.append(f"  - [{lp.REGRAS[r][0]}] {r} em {onde}: {lp.REGRAS[r][2]} ({det})")
    return "\n".join(l for l in linhas if l)


# ---------------------------------------------------------------- diagrama
def mermaid(i):
    nid = {x["nome"]: "n" + x["numero"].replace(".", "_").replace("-", "_") for x in i["acoes"]}
    for k in nid:  # ids só com caracteres seguros
        nid[k] = "".join(c if (c.isascii() and c.isalnum()) or c == "_" else "_" for c in nid[k])
    por = {}
    for x in i["acoes"]:
        por.setdefault((x["pai"], x["ramo"]), []).append(x)

    def rot(s):
        return str(s).replace('"', "'").replace("<", "&lt;").replace(">", "&gt;")

    g = i["gatilho"]
    icone = {"Recurrence": "⏰", "Request": "🌐"}.get(g["tipo"], "⚡") if g else ""
    L = ["```mermaid", "flowchart TD",
         f'    T(["{icone} {rot(g["nome"])}<br/>{rot(g["texto"][:60])}"])' if g else '    T(["(sem gatilho)"])']

    def emit(pai, ramo, ind):
        for x in por.get((pai, ramo), []):
            n, t = x["nome"], x["tipo"]
            if t in ("If", "Switch"):
                L.append(f'{ind}{nid[n]}{{"{x["numero"]}. {rot(n)}"}}')
                for r, _ in lp.blocos(x["acao"]):
                    if por.get((n, r)):
                        sid = f"{nid[n]}_{''.join(c if c.isascii() and c.isalnum() else '_' for c in r)}"
                        L.append(f'{ind}subgraph {sid}["{rot(r)}"]')
                        emit(n, r, ind + "    ")
                        L.append(f"{ind}end")
            elif t in ("Foreach", "Until", "Scope"):
                L.append(f'{ind}subgraph {nid[n]}["{x["numero"]}. {TIPO_PT[t]}: {rot(n)}"]')
                emit(n, None, ind + "    ")
                L.append(f"{ind}end")
            else:
                sub = con_pt(x["conector"]) or TIPO_PT.get(t, t)
                L.append(f'{ind}{nid[n]}["{x["numero"]}. {rot(n)}<br/><small>{rot(sub)}</small>"]')

    emit(None, None, "    ")
    for x in i["acoes"]:
        if not x["run_after"]:
            if x["pai"] is None:
                L.append(f"    T --> {nid[x['nome']]}")
            elif lp.idx_tipo(i, x["pai"]) in ("If", "Switch"):
                L.append(f'    {nid[x["pai"]]} -->|{rot(x["ramo"])}| {nid[x["nome"]]}')
        for dep, st in x["run_after"].items():
            if dep not in nid:
                continue
            if "Succeeded" in st:
                L.append(f"    {nid[dep]} --> {nid[x['nome']]}")
            else:
                L.append(f"    {nid[dep]} -.->|{' / '.join(STATUS_PT.get(s, s) for s in st)}| {nid[x['nome']]}")
    L.append("```")
    return "\n".join(L)


# ---------------------------------------------------------------- página
def documento(i):
    g = i["gatilho"]
    ag = g.get("agenda") if g else None
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    conns = ", ".join(con_pt(c) for c in i["conectores"]) or "nenhum conector gerenciado"
    L = ["---", "type: nota", "tags: [documentacao, logic-apps, gerado-automaticamente]", "area: projetos",
         f"created: {datetime.now():%Y-%m-%d}", f"updated: {datetime.now():%Y-%m-%d}", "---",
         f"# Documentação — {i['nome']}",
         f"> Gerada automaticamente a partir de `{i['arquivo']}` em {agora}. Conteúdo extraído do JSON por código "
         "(tools/logicapp_parser.py) e conferido por `tests/validar_docs.py`." + (" Exemplo fictício." if i.get("ficticio") else ""),
         "", "## Resumo",
         f"Roda {g['texto'] if g else '(sem gatilho)'}. Usa {conns}. Tem {len(i['acoes'])} ações"
         + (" e trata erros." if i["trata_erro"] else " e **não trata erros**.")
         + (f" Achados de boas práticas: **{len(i['achados'])}**." if i["achados"] else " Nenhum achado de boas práticas."),
         "", "## Gatilho", "| Nome | Tipo | Quando roda | Execuções/dia | Execuções/mês |", "|---|---|---|---|---|"]
    if g:
        L.append(f"| {g['nome']} | {TIPO_PT.get(g['tipo'], g['tipo'])} | {g['texto']} | "
                 f"{num(ag['por_dia']) if ag else '-'} | {num(ag['por_mes']) if ag else '-'} |")
        extras = []
        if g.get("operacao"):
            extras.append(f"Operação: {g['operacao']}")
        if g.get("campos_entrada"):
            extras.append("Campos esperados na chamada: " + ", ".join(f"`{c}`" for c in g["campos_entrada"]))
        if g.get("dividir_em"):
            extras.append(f"Divide a entrada em várias execuções (splitOn): `{g['dividir_em']}`")
        if g.get("condicoes"):
            extras.append("Só dispara se: " + "; ".join(f"`{c}`" for c in g["condicoes"]))
        if g.get("concorrencia"):
            extras.append(f"Execuções simultâneas permitidas: {g['concorrencia']}")
        if ag and ag.get("observacoes"):
            extras += [f"Atenção: {o}" for o in ag["observacoes"]]
        L += [""] + [f"- {e}" for e in extras] if extras else []
    L += ["", "## Fluxo", mermaid(i), "", "## Passo a passo",
          "Ordem de execução lida do JSON. Números como `3.S.1` indicam: passo 3, ramo **S**im, 1ª ação do ramo "
          "(`N` = Não, `P` = Padrão, ou o nome do caso no Switch).", ""]
    for x in i["acoes"]:
        h = "#" * min(3 + x["nivel"], 6)
        L.append(f"{h} {x['numero']}. {x['nome']} — {TIPO_PT.get(x['tipo'], x['tipo'])}")
        L.append(f"- **O que faz:** {o_que_faz(x)}")
        L.append(f"- **Quando roda:** {quando(x)}.")
        if x["pai"]:
            L.append(f"- **Dentro de:** `{x['pai']}`" + (f" → ramo {x['ramo']}" if x["ramo"] else ""))
        if x["usa"]:
            L.append("- **Usa dados de:** " + ", ".join(ref_pt(r, x["nome"]) for r in x["usa"]))
        usado = [y["nome"] for y in i["acoes"] if f"acao:{x['nome']}" in y["usa"]]
        if usado:
            L.append("- **Quem usa o resultado:** " + ", ".join(f"`{u}`" for u in usado))
        if x["paralelo_com"]:
            L.append("- **Roda em paralelo com:** " + ", ".join(f"`{p}`" for p in x["paralelo_com"]))
        rt = x["retentativa"]
        if rt["tipo"] != "default" and x["tipo"] not in lp.CONTAINERS:
            tentativas = f", {rt['tentativas']} tentativa(s)" if rt["tentativas"] else ""
            intervalo = f", intervalo {rt['intervalo']}" if rt["intervalo"] else ""
            L.append(f"- **Retentativa:** {RETRY_PT.get(rt['tipo'], rt['tipo'])}{tentativas}{intervalo}")
        if x["dados_protegidos"]:
            L.append("- **Dados ocultos no histórico:** " + ", ".join(x["dados_protegidos"]))
        L.append("")
    if i["variaveis"]:
        L += ["## Variáveis", "| Variável | Tipo | Valor inicial | Criada em | Alterada em |", "|---|---|---|---|---|"]
        L += [f"| {k} | {v['tipo']} | `{curto(v['inicial'], 40)}` | {v['criada_em']} | {', '.join(v['alterada_em']) or '-'} |"
              for k, v in i["variaveis"].items()]
        L.append("")
    L += ["## Parâmetros"]
    if i["parametros"]:
        L += ["| Nome | Tipo | Valor padrão |", "|---|---|---|"]
        L += [f"| {k} | {v['tipo']} | {'(protegido)' if str(v['tipo']).lower().startswith('secure') else curto(v['padrao'], 60)} |"
              for k, v in i["parametros"].items()]
    else:
        L.append("Nenhum parâmetro além das conexões.")
    c = i["cobranca"]
    L += ["", "## Custo (execuções cobradas)",
          "No plano Consumption, cada execução de gatilho e de ação é medida; dentro de loop, cada volta conta "
          "([Microsoft Learn](https://learn.microsoft.com/azure/logic-apps/logic-apps-pricing)).",
          "", "| Item | Valor |", "|---|---|",
          f"| Ações por execução (fora de loops; em condições, o ramo mais longo) | {c['fixas_por_execucao']} "
          f"(conector gerenciado: {c['conector_fixas']}) |"]
    for k, v in c["por_item_de_loop"].items():
        L.append(f"| Ações a cada item/volta de `{k}` | {v} |")
    if c["so_em_caso_de_falha"]:
        L.append(f"| Só rodam se algo falhar (não entram na conta) | {', '.join(c['so_em_caso_de_falha'])} |")
    if "execucoes_por_mes" in c:
        L.append(f"| Execuções do gatilho por mês | {num(c['execucoes_por_mes'])} |")
        L.append(f"| Ações fixas por mês (execuções × ações fixas) | {num(c['acoes_fixas_por_mes'])}"
                 + (" + as dos loops" if c["por_item_de_loop"] else "") + " |")
        L += custo_em_reais(i)
    L += ["", "## Ações", "| # | Ação | Tipo | Conector | Dentro de | Executa após |", "|---|---|---|---|---|---|"]
    for x in i["acoes"]:
        ra = "; ".join(f"{d} ({', '.join(s)})" for d, s in x["run_after"].items()) or "início do bloco"
        dentro = (f"{x['pai']}" + (f" → {x['ramo']}" if x["ramo"] else "")) if x["pai"] else "-"
        L.append(f"| {x['numero']} | {x['nome']} | {TIPO_PT.get(x['tipo'], x['tipo'])} | {con_pt(x['conector']) or '-'} | "
                 f"{dentro} | {ra} |")
    L += ["", "## Achados de boas práticas"]
    if i["achados"]:
        L += ["| Severidade | Regra | Categoria | Onde | Detalhe | Recomendação |", "|---|---|---|---|---|---|"]
        for r, onde, det in i["achados"]:
            sev, cat, desc, rec = lp.REGRAS[r]
            L.append(f"| {sev} | {r} | {cat} | {onde} | {desc} ({curto(mascara(det), 100)}) | {rec} |")
    else:
        L.append("Nenhum achado.")
    L += ["", "---", "↩︎ [[INDICE Logic Apps]]"]
    return "\n".join(L) + "\n"


PRECOS = ROOT / "relatorios" / "azure" / "precos_logicapps.json"


def custo_mes(i):
    """Custo do mês (gatilho + ações fixas, sem loops) com os preços oficiais trazidos pela Logic App de teste.
    Devolve None sem arquivo de preços ou sem agenda; {"erro": ...} se o arquivo vier em formato inesperado."""
    if not PRECOS.exists() or "execucoes_por_mes" not in i["cobranca"]:
        return None
    try:
        p = json.loads(PRECOS.read_text(encoding="utf-8"))
        tab = {}
        for item in p.get("precos", []):
            tab.setdefault(item["medidor"], []).append((float(item["a_partir_de"]), float(item["preco"])))
        nativa = sorted(tab["Consumption Built-in Actions"])
        conector = max(v for _, v in tab["Consumption Standard Connector Actions"])
    except (KeyError, ValueError, TypeError):
        return {"erro": "arquivo de preços em formato inesperado"}
    c, g = i["cobranca"], i["gatilho"]
    gratis = nativa[1][0] if len(nativa) > 1 else 0
    preco_nat = nativa[-1][1]
    gat_conector = bool(g and g["tipo"] in lp.CONECTOR_TIPOS)
    nat_mes = c["execucoes_por_mes"] * (c["fixas_por_execucao"] - c["conector_fixas"] + (0 if gat_conector else 1))
    con_mes = c["execucoes_por_mes"] * (c["conector_fixas"] + (1 if gat_conector else 0))
    custo = max(0, float(nat_mes) - gratis) * preco_nat + float(con_mes) * conector
    return {"custo": custo, "moeda": "R$" if p.get("moeda") == "BRL" else p.get("moeda", ""), "preco_nativa": preco_nat,
            "preco_conector": conector, "gratis": gratis, "regiao": p.get("regiao"),
            "consultado_em": str(p.get("consultado_em", ""))[:10]}


def br(v, casas=4):
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def custo_em_reais(i):
    """Converte as execuções em R$ com os preços oficiais trazidos pela Logic App de teste (se existirem)."""
    c = custo_mes(i)
    if c is None:
        return []
    if "erro" in c:
        return ["| Preços em R$ | arquivo de preços em formato inesperado |"]
    moeda = c["moeda"]
    return [f"| Preço por ação nativa | {moeda} {br(c['preco_nativa'])} (as primeiras {br(c['gratis'], 0)} do mês são grátis, "
            "somando todas as Logic Apps da assinatura) |",
            f"| Preço por ação de conector Standard | {moeda} {br(c['preco_conector'])} |",
            f"| Custo estimado por mês (gatilho + ações fixas, sem loops) | {moeda} {br(c['custo'], 2)} |",
            f"| Fonte dos preços | API oficial de preços do Azure, região {c['regiao']}, consultada pela Logic App "
            f"de teste em {c['consultado_em']} |"]


def indice(infos):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    L = ["---", "type: moc", "tags: [documentacao, logic-apps]", "area: projetos", "---",
         "# INDICE Logic Apps", f"> Gerado automaticamente em {agora}. Exemplos fictícios marcados com (exemplo).", "",
         "| Logic App | Quando roda | Conectores | Ações | Trata erro | Achados (A/M/B) |", "|---|---|---|---|---|---|"]
    for i in infos:
        cnt = {s: sum(1 for r, _, _ in i["achados"] if lp.REGRAS[r][0] == s) for s in ("Alta", "Média", "Baixa")}
        L.append(f"| [[{i['nome']}]]{' (exemplo)' if i.get('ficticio') else ''} | {i['gatilho']['texto'] if i['gatilho'] else '-'} | "
                 f"{', '.join(con_pt(c) for c in i['conectores']) or '-'} | {len(i['acoes'])} | "
                 f"{'sim' if i['trata_erro'] else 'não'} | {cnt['Alta']}/{cnt['Média']}/{cnt['Baixa']} |")
    L += ["", f"**Total de achados:** {sum(len(i['achados']) for i in infos)}"]
    return "\n".join(L) + "\n"


def gerar(hook=False):
    OUT.mkdir(parents=True, exist_ok=True)
    infos = [analisar(n) for n in nomes()]
    for i in infos:
        (OUT / f"{i['nome']}.md").write_text(documento(i), encoding="utf-8")
    (OUT / "INDICE Logic Apps.md").write_text(indice(infos), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "validar_docs.py")], capture_output=True, text=True,
                       encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    resultado = (r.stdout.strip().splitlines() or ["RESULTADO: sem saída"])[-1]
    tot = sum(len(i["achados"]) for i in infos)
    if hook:
        with (OUT / "hook.log").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%d/%m/%Y %H:%M:%S} | hook stop | {len(infos)} Logic Apps documentadas | "
                    f"{tot} achados | {resultado}\n")
        import historico  # registra no histórico do hub
        historico.evento("Documentação das Logic Apps", "ok" if "CONFIÁVEL" in resultado else "falhou",
                         resultado.split(":", 1)[-1].strip(), origem="hook do agente de documentação")
        print(f"[hook] Documentação gerada por código e validada: {resultado}")
        return 0
    print(f"{len(infos)} Logic Apps documentadas em docs/logicapps/ ({tot} achados de boas práticas)")
    print(indice(infos))
    print("--- Validação automática ---")
    print(r.stdout.strip())
    return r.returncode


def main(argv):
    utf8_stdout()
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "listar":
        for n in nomes():
            g = analisar(n)["gatilho"]
            print(f"- {n}: roda {g['texto'] if g else '(sem gatilho)'}")
    elif cmd == "resumo":
        nome = (argv[2] if len(argv) > 2 and argv[2] else os.environ.get("nome", "")).strip()
        if nome not in nomes():
            print(f"Logic App '{nome}' não encontrada. Disponíveis: {', '.join(nomes())}")
            return 1
        print(resumo_texto(analisar(nome)))
    elif cmd == "achados":
        tot = 0
        for n in nomes():
            for r, onde, det in analisar(n)["achados"]:
                sev, cat, desc, rec = lp.REGRAS[r]
                print(f"- [{sev}] {n} | {r} ({cat}) em {onde}: {desc} ({mascara(det)}). Recomendação: {rec}")
                tot += 1
        print(f"Total: {tot} achado(s).")
    elif cmd == "gerar":
        return gerar(hook="--hook" in argv)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
