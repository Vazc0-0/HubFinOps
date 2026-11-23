"""Leitor determinístico de Logic Apps (Workflow Definition Language).

Recebe o JSON de uma Logic App (o mesmo do "modo de exibição de código" do portal) e devolve
um dicionário estruturado com TUDO o que está nele: gatilho, agenda exata, cada ação na ordem
real de execução, de onde cada ação tira os dados, variáveis, parâmetros, conectores,
configurações de execução e riscos de boas práticas.

Nada aqui usa IA: é leitura do JSON. A IA só explica a partir desta saída.

Referências oficiais usadas para cada regra (Microsoft Learn):
  Esquema da linguagem ......... https://learn.microsoft.com/azure/logic-apps/workflow-definition-language-schema
  Tipos de gatilho e ação ...... https://learn.microsoft.com/azure/logic-apps/logic-apps-workflow-actions-triggers
  Variáveis .................... https://learn.microsoft.com/azure/logic-apps/logic-apps-create-variables-store-values
  Erros, runAfter, retentativa . https://learn.microsoft.com/azure/logic-apps/error-exception-handling
  Cobrança (medição) ........... https://learn.microsoft.com/azure/logic-apps/logic-apps-pricing
"""
from fractions import Fraction

CONTAINERS = ("Foreach", "Until", "Scope", "If", "Switch")
CONECTOR_TIPOS = ("ApiConnection", "ApiConnectionWebhook")
STATUS_ERRO = {"Failed", "TimedOut"}

# funções de expressão que apontam para outra ação pelo nome (1º argumento literal)
FUNC_ACAO = {"body", "outputs", "actions", "actionbody", "actionoutputs", "result"}
FUNC_GATILHO = {"triggerbody", "triggeroutputs", "trigger", "triggermultipartbody",
                "triggerformdatavalue", "triggerformdatamultiplevalues"}

DIAS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DIAS_PT = {"Monday": "segunda", "Tuesday": "terça", "Wednesday": "quarta", "Thursday": "quinta",
           "Friday": "sexta", "Saturday": "sábado", "Sunday": "domingo"}
UNID_PT = {"Second": ("segundo", "segundos"), "Minute": ("minuto", "minutos"), "Hour": ("hora", "horas"),
           "Day": ("dia", "dias"), "Week": ("semana", "semanas"), "Month": ("mês", "meses")}


# ----------------------------------------------------------------- expressões
def expressoes(valor):
    """Devolve os trechos de expressão de uma string da WDL.

    Regras oficiais: string que começa com '@' é uma expressão inteira; '@{...}' dentro de
    uma string é interpolação; '@@' no início é o caractere '@' literal (não é expressão).
    """
    if not isinstance(valor, str) or "@" not in valor:
        return []
    if valor.startswith("@@"):
        return []
    if valor.startswith("@") and not valor.startswith("@{"):
        return [valor[1:]]
    out, i = [], 0
    while True:
        j = valor.find("@{", i)
        if j < 0:
            return out
        k, prof, aspas = j + 2, 1, False
        while k < len(valor) and prof:
            c = valor[k]
            if aspas:
                if c == "'":
                    if k + 1 < len(valor) and valor[k + 1] == "'":
                        k += 1
                    else:
                        aspas = False
            elif c == "'":
                aspas = True
            elif c == "{":
                prof += 1
            elif c == "}":
                prof -= 1
            k += 1
        out.append(valor[j + 2:k - 1])
        i = k


def chamadas(expr):
    """Lista (função, 1º argumento literal ou None) de cada chamada de função, ignorando
    o que está dentro de textos entre aspas."""
    out, i, n = [], 0, len(expr)
    while i < n:
        c = expr[i]
        if c == "'":  # pula texto literal (com '' como aspa escapada)
            i += 1
            while i < n:
                if expr[i] == "'":
                    if i + 1 < n and expr[i + 1] == "'":
                        i += 2
                        continue
                    break
                i += 1
            i += 1
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            nome, k = expr[i:j], j
            while k < n and expr[k] == " ":
                k += 1
            if k < n and expr[k] == "(":
                k += 1
                while k < n and expr[k] == " ":
                    k += 1
                arg = None
                if k < n and expr[k] == "'":
                    m, buf = k + 1, []
                    while m < n:
                        if expr[m] == "'":
                            if m + 1 < n and expr[m + 1] == "'":
                                buf.append("'")
                                m += 2
                                continue
                            break
                        buf.append(expr[m])
                        m += 1
                    arg = "".join(buf)
                out.append((nome.lower(), arg))
            i = j
            continue
        i += 1
    return out


def strings(obj, caminho=()):
    """Percorre um objeto JSON devolvendo (caminho, string) de todas as strings (chaves inclusas)."""
    if isinstance(obj, str):
        yield caminho, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield caminho + (k,), k
            yield from strings(v, caminho + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from strings(v, caminho + (i,))


def literal_sem_expressoes(valor):
    """Parte literal de uma string (tira as expressões)."""
    if not isinstance(valor, str):
        return ""
    if valor.startswith("@") and not valor.startswith("@{") and not valor.startswith("@@"):
        return ""
    s = valor
    for e in expressoes(valor):
        s = s.replace("@{" + e + "}", " ")
    return s


# ----------------------------------------------------------------- agenda (gatilho Recurrence)
def _lista(v, conv=int):
    if v is None or v == "":
        return []
    if isinstance(v, str):
        v = [p.strip() for p in v.split(",") if p.strip()]
    if not isinstance(v, list):
        v = [v]
    return [conv(x) for x in v]


def agenda(rec):
    """Agenda exata de uma recorrência: execuções por dia/semana/mês (frações exatas) e texto."""
    f = rec.get("frequency")
    n = int(rec.get("interval", 1) or 1)
    sch = rec.get("schedule") or {}
    usa_sch = f in ("Day", "Week")  # doc: horas/minutos valem para Day/Week; dias da semana só para Week
    H = sorted(set(_lista(sch.get("hours")))) if usa_sch else []
    M = sorted(set(_lista(sch.get("minutes")))) if usa_sch else []
    W = [d for d in DIAS if d in set(_lista(sch.get("weekDays"), str))] if f == "Week" else []
    start = rec.get("startTime") or ""
    hora_ini = start[11:16] if len(start) >= 16 else ""
    vezes_dia = (len(H) or 1) * (len(M) or 1)
    por_semana = {
        "Second": Fraction(7 * 86400, n), "Minute": Fraction(7 * 1440, n), "Hour": Fraction(7 * 24, n),
        "Day": Fraction(7 * vezes_dia, n), "Week": Fraction((len(W) or 1) * vezes_dia, n),
        "Month": Fraction(12 * 7, 365 * n),
    }.get(f)
    if por_semana is None:
        return {"frequencia": f, "intervalo": n, "texto": f"frequência desconhecida '{f}'",
                "por_dia": None, "por_semana": None, "por_mes": None, "horarios": [], "dias_semana": []}
    horarios = [f"{h:02d}:{m:02d}" for h in H for m in (M or [int(hora_ini[3:5]) if hora_ini else 0])] if H else \
        ([f"{int(hora_ini[:2]):02d}:{m:02d}" for m in M] if M and hora_ini else [])
    obs = []
    if usa_sch and M and not H:
        obs.append("agenda com minutos mas sem horas: o horário exato depende da hora de início (startTime)")
    if not usa_sch and (sch.get("hours") or sch.get("minutes") or sch.get("weekDays")):
        obs.append(f"'schedule' é ignorado com frequência {f} (só vale para Day/Week)")
    if f == "Day" and sch.get("weekDays"):
        obs.append("'weekDays' é ignorado com frequência Day (só vale para Week)")
    sing, plur = UNID_PT[f]
    if n == 1:
        base = {"Second": "a cada segundo", "Minute": "a cada minuto", "Hour": "a cada hora", "Day": "todo dia",
                "Week": "toda semana", "Month": "todo mês"}[f]
    else:
        base = f"a cada {n} {plur}"
    txt = base
    if W:
        txt += " às " + _junta([DIAS_PT[d] + "s" for d in W])
    if horarios:
        txt += ", às " + _junta(horarios)
    elif f in ("Day", "Week", "Month") and hora_ini:
        txt += f", às {hora_ini}"
    if f == "Month" and len(start) >= 10:
        txt += f" (no dia {int(start[8:10])})"
    if rec.get("timeZone"):
        txt += f" — fuso {rec['timeZone']}"
    por_dia = por_semana / 7
    return {"frequencia": f, "intervalo": n, "texto": txt, "horarios": horarios, "dias_semana": W,
            "por_dia": por_dia, "por_semana": por_semana, "por_mes": por_dia * Fraction(365, 12),
            "inicio": start or None, "fuso": rec.get("timeZone"), "observacoes": obs}


def _junta(itens):
    itens = list(itens)
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


# ----------------------------------------------------------------- conectores e operações
def conector_de(a):
    if a.get("type") not in CONECTOR_TIPOS:
        return None
    host = ((a.get("inputs") or {}).get("host") or {}).get("connection") or {}
    for _, s in strings(host):
        # formato oficial: "@parameters('$connections')['<conector>']['connectionId']"
        if "$connections" in s:
            i = s.find("['")
            if i >= 0:
                return s[i + 2:s.find("']", i)]
    return host.get("referenceName")  # formato do Logic App Standard


def caminho_legivel(path):
    """Troca @{encodeURIComponent('x')} por x para leitura humana."""
    if not isinstance(path, str):
        return ""
    out = path
    for e in expressoes(path):
        miolo = e.strip()
        while miolo.lower().startswith("encodeuricomponent(") and miolo.endswith(")"):
            miolo = miolo[len("encodeuricomponent("):-1].strip()
        cs = chamadas(miolo)
        if miolo.startswith("'") and miolo.endswith("'") and not cs:
            out = out.replace("@{" + e + "}", miolo[1:-1].replace("''", "'"))
        elif len(cs) == 1 and cs[0][0] == "parameters" and cs[0][1] and miolo.endswith(")"):
            out = out.replace("@{" + e + "}", "{parâmetro " + cs[0][1] + "}")
    return out


def operacao_conector(con, metodo, path):
    """Nome da operação de conectores comuns (pela rota da API gerenciada); senão, MÉTODO rota."""
    m, p = (metodo or "").upper(), caminho_legivel(path)
    partes = [x for x in p.split("/") if x]
    if con == "office365" and m == "POST" and p.rstrip("/").endswith("/Mail"):
        return "Enviar um e-mail (V2)" if "/v2/" in p else "Enviar um e-mail"
    if con in ("sharepointonline", "excelonlinebusiness") and "tables" in partes:
        tab = partes[partes.index("tables") + 1] if partes.index("tables") + 1 < len(partes) else "?"
        alvo = "lista" if con == "sharepointonline" else "tabela"
        if partes[-1] == "items" and m == "GET":
            return f"Obter itens da {alvo} '{tab}'"
        if partes[-1] == "items" and m == "POST":
            return f"Criar item na {alvo} '{tab}'"
        if "items" in partes and m == "PATCH":
            return f"Atualizar item da {alvo} '{tab}'"
        if "items" in partes and m == "DELETE":
            return f"Excluir item da {alvo} '{tab}'"
        if partes[-1] == "onnewitems":
            return f"Quando um item é criado na {alvo} '{tab}'"
        if partes[-1] == "onupdateditems":
            return f"Quando um item é criado ou modificado na {alvo} '{tab}'"
    return f"{m} {p}".strip()


# ----------------------------------------------------------------- leitura da definição
def blocos(a):
    """Blocos de ações filhas de uma ação de controle: lista de (ramo, dict de ações)."""
    t = a.get("type")
    if t in ("Foreach", "Until", "Scope"):
        return [(None, a.get("actions") or {})]
    if t == "If":
        return [("Sim", a.get("actions") or {}), ("Não", (a.get("else") or {}).get("actions") or {})]
    if t == "Switch":
        out = [(cn, c.get("actions") or {}) for cn, c in (a.get("cases") or {}).items()]
        return out + [("Padrão", (a.get("default") or {}).get("actions") or {})]
    return []


def ordem_bloco(acoes, problemas):
    """Ordem real de execução dentro de um bloco (ordenação topológica pelo runAfter).
    Empate: ordem em que aparecem no arquivo (é a ordem do designer)."""
    nomes = list(acoes)
    pend = {n: set((acoes[n].get("runAfter") or {}).keys()) for n in nomes}
    for n, deps in pend.items():
        for d in sorted(deps - set(nomes)):
            problemas.append(("RUNAFTER_INVALIDO", n, f"runAfter aponta para '{d}', que não está no mesmo bloco"))
        pend[n] = deps & set(nomes)
    feitas, ordem = set(), []
    while len(ordem) < len(nomes):
        prontas = [n for n in nomes if n not in feitas and pend[n] <= feitas]
        if not prontas:
            resto = [n for n in nomes if n not in feitas]
            problemas.append(("RUNAFTER_INVALIDO", resto[0], "dependência circular no runAfter: " + ", ".join(resto)))
            prontas = resto[:1]
        for n in prontas:
            feitas.add(n)
            ordem.append(n)
    return ordem


def ler(doc):
    """Lê a definição completa. Aceita o JSON exportado (com "definition") ou só a definição."""
    d = doc.get("definition", doc) if isinstance(doc, dict) else {}
    problemas = []
    acoes, idx = [], {}

    def visita(dic, pai, ramo, nivel, prefixo, loops):
        for k, nome in enumerate(ordem_bloco(dic, problemas), 1):
            a = dic[nome]
            numero = f"{prefixo}{k}"
            reg = {"nome": nome, "tipo": a.get("type"), "pai": pai, "ramo": ramo, "nivel": nivel,
                   "numero": numero, "loops": list(loops), "acao": a,
                   "run_after": {d: list(s) for d, s in (a.get("runAfter") or {}).items()}}
            if nome in idx:
                problemas.append(("NOME_DUPLICADO", nome, "duas ações com o mesmo nome"))
            idx[nome] = reg
            acoes.append(reg)
            novos_loops = loops + [nome] if a.get("type") in ("Foreach", "Until") else loops
            for r, filhos in blocos(a):
                visita(filhos, nome, r, nivel + 1, numero + "." + (_sigla(r, a.get("type")) + "." if r else ""),
                       novos_loops)

    visita(d.get("actions") or {}, None, None, 0, "", [])

    # paralelismo: irmãos (mesmo pai e ramo) que dependem exatamente das mesmas ações
    def mesmo_ponto(x, y):  # rodam ao mesmo tempo: mesmo bloco, mesmas dependências e status compatíveis
        if (x["pai"], x["ramo"]) != (y["pai"], y["ramo"]) or set(x["run_after"]) != set(y["run_after"]):
            return False
        return all(set(x["run_after"][d]) & set(y["run_after"][d]) for d in x["run_after"])

    for x in acoes:
        x["paralelo_com"] = sorted(y["nome"] for y in acoes if y is not x and mesmo_ponto(x, y))

    # gatilho
    trig_nome, trig = next(iter((d.get("triggers") or {}).items()), (None, {}))
    gatilho = ler_gatilho(trig_nome, trig) if trig_nome else None

    params = {k: {"tipo": v.get("type"), "padrao": v.get("defaultValue")}
              for k, v in (d.get("parameters") or {}).items() if k != "$connections"}

    variaveis = {}
    for x in acoes:
        if x["tipo"] == "InitializeVariable":
            for v in ((x["acao"].get("inputs") or {}).get("variables") or []):
                variaveis[v.get("name")] = {"tipo": (v.get("type") or "").lower(), "inicial": v.get("value"),
                                            "criada_em": x["nome"], "alterada_em": []}
    for x in acoes:
        if x["tipo"] in ("SetVariable", "IncrementVariable", "DecrementVariable",
                         "AppendToArrayVariable", "AppendToStringVariable"):
            nv = (x["acao"].get("inputs") or {}).get("name")
            if nv in variaveis:
                variaveis[nv]["alterada_em"].append(x["nome"])
            else:
                problemas.append(("REFERENCIA_INEXISTENTE", x["nome"], f"altera a variável '{nv}', que não foi inicializada"))

    for x in acoes:
        x["conector"] = conector_de(x["acao"])
        x["detalhes"] = detalhes(x, idx)
        x["usa"] = referencias(x, idx)
        inp = x["acao"].get("inputs") if isinstance(x["acao"].get("inputs"), dict) else {}
        rp = inp.get("retryPolicy") or {}
        x["retentativa"] = {"tipo": (rp.get("type") or "default").lower(), "tentativas": rp.get("count"),
                            "intervalo": rp.get("interval")}
        rc = x["acao"].get("runtimeConfiguration") or {}
        x["dados_protegidos"] = sorted((rc.get("secureData") or {}).get("properties") or [])
        x["opcoes"] = x["acao"].get("operationOptions")

    # referências que apontam para o que não existe
    nomes_acoes = set(idx)
    for x in acoes:
        for r in x["usa"]:
            tipo, _, alvo = r.partition(":")
            if (tipo == "acao" and alvo not in nomes_acoes) or (tipo == "variavel" and alvo not in variaveis) \
                    or (tipo == "parametro" and alvo not in params) or (tipo == "item" and alvo == "?"):
                problemas.append(("REFERENCIA_INEXISTENTE", x["nome"], f"usa {r}, que não existe no fluxo"))
    if gatilho:
        for r in gatilho["usa"]:
            tipo, _, alvo = r.partition(":")
            if tipo == "parametro" and alvo not in params:
                problemas.append(("REFERENCIA_INEXISTENTE", trig_nome, f"usa {r}, que não existe no fluxo"))

    conectores = sorted({x["conector"] for x in acoes if x["conector"]} |
                        ({gatilho["conector"]} if gatilho and gatilho.get("conector") else set()))
    trata_erro = any(set(s) & STATUS_ERRO for x in acoes for s in x["run_after"].values())
    info = {"gatilho": gatilho, "acoes": acoes, "parametros": params, "variaveis": variaveis,
            "conectores": conectores, "trata_erro": trata_erro, "problemas": problemas,
            "cobranca": cobranca(acoes, gatilho)}
    info["achados"] = achados(info)
    return info


def _sigla(ramo, tipo):
    if tipo == "If":
        return "S" if ramo == "Sim" else "N"
    return "P" if ramo == "Padrão" else ramo  # Switch: nome do caso


def ler_gatilho(nome, t):
    tipo = t.get("type")
    inp = t.get("inputs") if isinstance(t.get("inputs"), dict) else {}
    g = {"nome": nome, "tipo": tipo, "kind": t.get("kind"), "conector": None, "operacao": None,
         "agenda": None, "texto": "", "usa": [], "dividir_em": t.get("splitOn"),
         "condicoes": [c.get("expression") for c in (t.get("conditions") or [])],
         "concorrencia": ((t.get("runtimeConfiguration") or {}).get("concurrency") or {}).get("runs"),
         "opcoes": t.get("operationOptions")}
    if tipo == "Recurrence":
        g["agenda"] = agenda(t.get("recurrence") or {})
        g["texto"] = g["agenda"]["texto"]
    elif tipo == "Request":
        metodo = (inp.get("method") or "qualquer método").upper() if inp.get("method") else "qualquer método"
        g["texto"] = f"sob demanda, quando receber uma chamada HTTP ({metodo})"
        g["campos_entrada"] = sorted(((inp.get("schema") or {}).get("properties") or {}).keys())
    elif tipo in ("ApiConnection", "Http"):
        g["conector"] = conector_de(t) if tipo == "ApiConnection" else None
        g["agenda"] = agenda(t.get("recurrence") or {}) if t.get("recurrence") else None
        alvo = g["conector"] or inp.get("uri", "um endpoint HTTP")
        g["operacao"] = operacao_conector(g["conector"], inp.get("method"), inp.get("path")) if tipo == "ApiConnection" \
            else f"{(inp.get('method') or 'GET').upper()} {inp.get('uri', '')}"
        g["texto"] = f"verifica {alvo} " + (g["agenda"]["texto"] if g["agenda"] else "(sem recorrência definida)") + \
            " e dispara quando há novidade"
    elif tipo in ("ApiConnectionWebhook", "HttpWebhook"):
        g["conector"] = conector_de(t) if tipo == "ApiConnectionWebhook" else None
        g["texto"] = f"quando {g['conector'] or 'o serviço externo'} avisar por webhook (evento)"
    else:
        g["texto"] = f"gatilho do tipo {tipo}"
    for _, s in strings(t):
        for e in expressoes(s):
            for f, arg in chamadas(e):
                if f == "parameters" and arg and arg != "$connections":
                    g["usa"].append(f"parametro:{arg}")
    g["usa"] = sorted(set(g["usa"]))
    return g


def referencias(x, idx):
    """De onde a ação tira dados: outras ações, gatilho, variáveis, parâmetros, item do loop."""
    a, t = x["acao"], x["tipo"]
    if t in CONTAINERS:  # só os campos da própria ação de controle (os filhos têm as deles)
        alvo = {k: a.get(k) for k in ("foreach", "expression", "limit", "inputs") if k in a}
    else:
        alvo = {k: v for k, v in a.items() if k not in ("runAfter", "type")}
    refs = set()
    for caminho, s in strings(alvo):
        for e in expressoes(s):
            for f, arg in chamadas(e):
                if f in FUNC_ACAO and arg:
                    refs.add(f"acao:{arg}")
                elif f in FUNC_GATILHO:
                    refs.add("gatilho")
                elif f == "variables" and arg:
                    refs.add(f"variavel:{arg}")
                elif f == "parameters" and arg and arg != "$connections":
                    refs.add(f"parametro:{arg}")
                elif f in ("items", "iterationindexes") and arg:
                    refs.add(f"item:{arg}")
                elif f == "item":
                    # item() em where/select/columns de Filtrar/Selecionar/Tabela = elemento da própria matriz
                    proprio = len(caminho) >= 2 and caminho[0] == "inputs" and (
                        (t == "Query" and caminho[1] == "where") or (t == "Select" and caminho[1] == "select")
                        or (t == "Table" and caminho[1] == "columns"))
                    laco = next((l for l in reversed(x["loops"]) if idx[l]["tipo"] == "Foreach"), None)
                    refs.add(f"item:{x['nome']}" if proprio else f"item:{laco}" if laco else "item:?")
    return sorted(refs)


def detalhes(x, idx):
    """Configuração de cada tipo de ação, em campos legíveis (para a documentação)."""
    a, t = x["acao"], x["tipo"]
    inp = a.get("inputs")
    i = inp if isinstance(inp, dict) else {}
    if t == "Http":
        return {"metodo": (i.get("method") or "").upper(), "uri": i.get("uri"), "consulta": i.get("queries") or {},
                "cabecalhos": sorted((i.get("headers") or {}).keys()), "tem_corpo": "body" in i,
                "autenticacao": (i.get("authentication") or {}).get("type")}
    if t in CONECTOR_TIPOS:
        con = conector_de(a)
        return {"operacao": operacao_conector(con, i.get("method"), i.get("path")),
                "metodo": (i.get("method") or "").upper(), "rota": caminho_legivel(i.get("path")),
                "campos": sorted((i.get("body") or {}).keys()) if isinstance(i.get("body"), dict) else [],
                "consulta": i.get("queries") or {}}
    if t == "Foreach":
        rc = ((a.get("runtimeConfiguration") or {}).get("concurrency") or {}).get("repetitions")
        seq = rc == 1 or a.get("operationOptions") == "Sequential"
        return {"sobre": a.get("foreach"), "sequencial": seq, "paralelismo": 1 if seq else rc}
    if t == "Until":
        lim = a.get("limit") or {}
        return {"condicao": a.get("expression"), "limite_vezes": lim.get("count"), "limite_tempo": lim.get("timeout")}
    if t == "If":
        return {"condicao": condicao_texto(a.get("expression"))}
    if t == "Switch":
        return {"expressao": a.get("expression"),
                "casos": {cn: c.get("case") for cn, c in (a.get("cases") or {}).items()},
                "tem_padrao": bool(((a.get("default") or {}).get("actions")))}
    if t == "Scope":
        return {}
    if t == "InitializeVariable":
        return {"variaveis": [{"nome": v.get("name"), "tipo": (v.get("type") or "").lower(), "valor": v.get("value")}
                              for v in (i.get("variables") or [])]}
    if t in ("SetVariable", "IncrementVariable", "DecrementVariable", "AppendToArrayVariable", "AppendToStringVariable"):
        return {"variavel": i.get("name"), "valor": i.get("value")}
    if t == "Compose":
        return {"entrada": inp}
    if t == "ParseJson":
        props = ((i.get("schema") or {}).get("properties") or {})
        return {"conteudo": i.get("content"), "campos": {k: (v or {}).get("type") for k, v in props.items()}}
    if t == "Query":
        return {"de": i.get("from"), "onde": i.get("where")}
    if t == "Select":
        sel = i.get("select")
        return {"de": i.get("from"), "mapa": sorted(sel.keys()) if isinstance(sel, dict) else sel}
    if t == "Join":
        return {"de": i.get("from"), "separador": i.get("joinWith")}
    if t == "Table":
        cols = i.get("columns")
        return {"formato": i.get("format"), "de": i.get("from"),
                "colunas": [c.get("header") for c in cols] if isinstance(cols, list) else "automáticas"}
    if t == "Response":
        return {"status": i.get("statusCode", 200), "tem_corpo": "body" in i}
    if t == "Terminate":
        return {"status": i.get("runStatus"), "erro": (i.get("runError") or {}).get("message")}
    if t == "Wait":
        iv = i.get("interval") or {}
        return {"intervalo": f"{iv.get('count')} {iv.get('unit')}" if iv else None,
                "ate": (i.get("until") or {}).get("timestamp")}
    if t == "Workflow":
        return {"fluxo_filho": ((i.get("host") or {}).get("workflow") or {}).get("id"),
                "gatilho_filho": (i.get("host") or {}).get("triggerName")}
    if t == "Function":
        return {"funcao": (i.get("function") or {}).get("id"), "metodo": (i.get("method") or "POST").upper()}
    if t == "JavaScriptCode":
        return {"linhas_de_codigo": len(str(i.get("code", "")).splitlines())}
    return {"entradas": sorted(i.keys())}


OPS = {"equals": "=", "not": "não", "greater": ">", "greaterOrEquals": ">=", "less": "<", "lessOrEquals": "<=",
       "contains": "contém", "startsWith": "começa com", "endsWith": "termina com"}


def condicao_texto(expr):
    """Condição do If em texto (formato do designer: {"and": [{"greater": [a, b]}]})."""
    if isinstance(expr, str):
        return expr
    if not isinstance(expr, dict) or not expr:
        return str(expr)
    op, args = next(iter(expr.items()))
    if op in ("and", "or"):
        return f" {'E' if op == 'and' else 'OU'} ".join(f"({condicao_texto(x)})" for x in args)
    if op == "not":
        return f"NÃO ({condicao_texto(args)})"
    if isinstance(args, list) and len(args) == 2:
        return f"{_curto(args[0])} {OPS.get(op, op)} {_curto(args[1])}"
    return f"{op}({args})"


def _curto(v):
    return v if isinstance(v, str) else repr(v)


# ----------------------------------------------------------------- cobrança (estimativa de execuções)
def cobranca(acoes, gatilho):
    """Quantas operações cobradas cada execução gera (modelo Consumption: cada ação executada
    conta; dentro de loop conta uma vez por item; a própria ação de loop conta 1).
    Em If/Switch considera o ramo com mais ações (estimativa máxima)."""
    porfilhos = {}
    for x in acoes:
        porfilhos.setdefault((x["pai"], x["ramo"]), []).append(x)

    so_falha = []

    def so_em_falha(x):
        # roda só no caminho de erro: depende de uma ação SEM o status Succeeded (ex.: só "Failed"),
        # ou de outra ação que já é só de erro (ex.: Encerrar depois de Registrar_falha)
        return any("Succeeded" not in s or d in so_falha for d, s in x["run_after"].items())

    def conta(pai, ramo):
        tot = {}
        for x in porfilhos.get((pai, ramo), []):
            if so_em_falha(x):
                so_falha.append(x["nome"])
                continue
            cat = "conector" if x["tipo"] in CONECTOR_TIPOS else "nativa"
            _soma(tot, ((), cat), 1)
            ramos = [r for r, _ in blocos(x["acao"])]
            if x["tipo"] in ("If", "Switch"):
                melhores = [conta(x["nome"], r) for r in ramos]
                if melhores:
                    maior = max(melhores, key=lambda d: sum(d.values()))
                    for k, v in maior.items():
                        _soma(tot, k, v)
            elif ramos:
                filho = conta(x["nome"], None)
                for (loops, cat2), v in filho.items():
                    chave = ((x["nome"],) + loops if x["tipo"] in ("Foreach", "Until") else loops, cat2)
                    _soma(tot, chave, v)
        return tot

    tot = conta(None, None)
    fixas = sum(v for (l, _), v in tot.items() if not l)
    por_loop = {}
    for (l, _cat), v in tot.items():
        if l:
            por_loop[" × ".join(l)] = por_loop.get(" × ".join(l), 0) + v
    out = {"fixas_por_execucao": fixas,
           "conector_fixas": sum(v for (l, c), v in tot.items() if not l and c == "conector"),
           "por_item_de_loop": por_loop, "so_em_caso_de_falha": sorted(so_falha)}
    ag = gatilho.get("agenda") if gatilho else None
    if ag and ag.get("por_mes") is not None:
        out["execucoes_por_mes"] = ag["por_mes"]
        out["acoes_fixas_por_mes"] = ag["por_mes"] * fixas
        out["gatilho_verificacoes_por_mes"] = ag["por_mes"]  # cada disparo/verificação do gatilho é medida
    return out


def _soma(d, k, v):
    d[k] = d.get(k, 0) + v


# ----------------------------------------------------------------- riscos de boas práticas
REGRAS = {
    "NOME_DUPLICADO": ("Alta", "Confiabilidade",
        "Duas ações com o mesmo nome: as expressões não sabem qual usar.",
        "Renomear uma das ações (o nome precisa ser único no fluxo inteiro)."),
    "REFERENCIA_INEXISTENTE": ("Alta", "Confiabilidade",
        "Uma expressão aponta para ação, variável ou parâmetro que não existe no fluxo.",
        "Corrigir o nome na expressão; o fluxo falha ao chegar nessa ação."),
    "RUNAFTER_INVALIDO": ("Alta", "Confiabilidade",
        "O 'executar após' (runAfter) aponta para ação fora do mesmo bloco, inexistente ou em ciclo.",
        "Uma ação só pode rodar após ações do mesmo bloco; ajustar o runAfter no designer."),
    "SEGREDO_NA_URL": ("Alta", "Segurança",
        "Chave/segredo exposto na URL de uma chamada HTTP (code=, sig=, key=).",
        "Guardar a chave no Azure Key Vault ou usar identidade gerenciada; nunca no JSON do fluxo."),
    "SEGREDO_NO_CABECALHO": ("Alta", "Segurança",
        "Chave/token escrito direto no cabeçalho de uma chamada HTTP.",
        "Ler o valor de um parâmetro seguro (securestring) ou do Key Vault."),
    "RECORRENCIA_FREQUENTE": ("Média", "Custo",
        "Gatilho roda com muita frequência (96 vezes por dia ou mais); cada execução e cada ação são cobradas.",
        "Ajustar a recorrência à necessidade real (ex.: relatório semanal → 1x por semana)."),
    "SEM_RETENTATIVA": ("Média", "Confiabilidade",
        "Política de retentativa desligada (retryPolicy 'none'): falha passageira (408/429/5xx) derruba a execução.",
        "Remover o 'none' para voltar à política padrão (até 4 retentativas) ou definir uma política explícita."),
    "SEM_TRATAMENTO_DE_ERRO": ("Média", "Confiabilidade",
        "Nenhuma ação roda após falha (runAfter Failed/TimedOut): erros passam em silêncio.",
        "Agrupar as ações num Escopo e adicionar uma ação de aviso com 'executar após' = Falhou/Tempo esgotado."),
    "VARIAVEL_EM_LOOP_PARALELO": ("Média", "Confiabilidade",
        "Variável alterada (definir/acrescentar) dentro de 'Para cada' que roda em paralelo: o resultado pode variar.",
        "Configurar o loop como sequencial (paralelismo 1) ou usar Compor/Selecionar em vez de variável."),
    "DESTINATARIO_FIXO": ("Baixa", "Manutenção",
        "Endereço de e-mail escrito direto na ação.",
        "Mover o destinatário para um parâmetro do fluxo (ou lista no SharePoint)."),
}
ORDEM_SEV = {"Alta": 0, "Média": 1, "Baixa": 2}
CABECALHOS_SECRETOS = {"authorization", "x-functions-key", "api-key", "ocp-apim-subscription-key", "x-api-key"}


def achados(info):
    out = list(info["problemas"])
    g = info["gatilho"]
    if g and g.get("agenda") and g["agenda"]["por_dia"] is not None and g["agenda"]["por_dia"] >= 96:
        out.append(("RECORRENCIA_FREQUENTE", g["nome"], f"{_num(g['agenda']['por_dia'])} execuções por dia"))
    for x in info["acoes"]:
        a = x["acao"]
        inp = a.get("inputs") if isinstance(a.get("inputs"), dict) else {}
        if x["tipo"] in ("Http", "HttpWebhook") and _tem_chave_na_url(inp.get("uri")):
            out.append(("SEGREDO_NA_URL", x["nome"], "parâmetro de chave na URI"))
        for h, v in (inp.get("headers") or {}).items() if x["tipo"] in ("Http", "HttpWebhook") else []:
            if h.lower() in CABECALHOS_SECRETOS and isinstance(v, str) and literal_sem_expressoes(v).strip():
                out.append(("SEGREDO_NO_CABECALHO", x["nome"], f"cabeçalho {h}"))
        if x["retentativa"]["tipo"] == "none":
            out.append(("SEM_RETENTATIVA", x["nome"], "retryPolicy: none"))
        if x["conector"] == "office365" and isinstance(inp.get("body"), dict):
            for campo in ("To", "Cc", "Bcc"):
                lit = literal_sem_expressoes(inp["body"].get(campo))
                if "@" in lit:
                    out.append(("DESTINATARIO_FIXO", x["nome"], f"{campo}: {lit.strip()}"))
        if x["tipo"] in ("SetVariable", "AppendToArrayVariable", "AppendToStringVariable"):
            for lp in x["loops"]:
                laco = next(y for y in info["acoes"] if y["nome"] == lp)
                if laco["tipo"] == "Foreach" and not laco["detalhes"]["sequencial"]:
                    out.append(("VARIAVEL_EM_LOOP_PARALELO", x["nome"],
                                f"altera '{x['detalhes']['variavel']}' dentro de '{lp}' (paralelo)"))
                    break
    if info["acoes"] and not info["trata_erro"]:
        out.append(("SEM_TRATAMENTO_DE_ERRO", "(fluxo inteiro)", "nenhum runAfter com Failed/TimedOut"))
    out.sort(key=lambda r: ORDEM_SEV[REGRAS[r[0]][0]])
    return out


def _tem_chave_na_url(uri):
    lit = literal_sem_expressoes(uri) if isinstance(uri, str) else ""
    q = lit.split("?", 1)[1] if "?" in lit else ""
    for par in q.split("&"):
        k, _, v = par.partition("=")
        if k.strip().lower() in ("code", "sig", "key", "api-key", "apikey") and v.strip():
            return True
    return False


def _num(f):
    if f is None:
        return "-"
    f = Fraction(f)
    if f.denominator == 1:
        return f"{f.numerator:,}".replace(",", ".")
    return f"{float(f):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def idx_tipo(info, nome):
    """Tipo da ação pelo nome (atalho para a documentação)."""
    return next((x["tipo"] for x in info["acoes"] if x["nome"] == nome), None)
