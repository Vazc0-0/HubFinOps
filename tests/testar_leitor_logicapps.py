"""Bateria de testes do leitor de Logic Apps (tools/logicapp_parser.py) e da documentação gerada.

O objetivo é provar que a leitura do JSON é exata antes de usar com Logic Apps reais.
Cada parte compara o que o leitor extraiu com uma resposta conhecida (gabarito):

  1. Agendas ........... 17 recorrências com execuções por dia/semana/mês calculadas à mão
  2. Expressões ........ 25 casos de referência entre ações (@, @{...}, @@, aspas, maiúsculas...)
  3. Gatilhos .......... um de cada tipo oficial
  4. Fluxos completos .. 2 fluxos com gabarito escrito à mão (todos os tipos de ação; 14 problemas plantados)
  5. Exemplos oficiais . os exemplos JSON da página de referência da Microsoft
  6. Exemplos do projeto as 3 Logic Apps de demonstração contra o gabarito de achados
  7. Aleatório ........ milhares de fluxos gerados com a resposta conhecida (estrutura, ordem, dados usados)
  8. Mutação .......... estraga fluxos válidos de propósito e confere se o leitor percebe
  9. Documentação ...... toda ação aparece na página, no diagrama e na tabela; nenhum segredo vaza
 10. Logic App real .... se logicapps/reais/la-precos-logicapps.json existir (baixado do Azure), lê igual ao gabarito

Uso:  python tests/testar_leitor_logicapps.py            (padrão: 2000 fluxos aleatórios)
      python tests/testar_leitor_logicapps.py 10000      (mais fluxos)
"""
import json
import random
import re
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import doc_logicapp as dl  # noqa: E402
import logicapp_parser as lp  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CASOS = ROOT / "tests" / "casos_logicapps"
falhas = []
contagem = {}


def confere(parte, ok, msg):
    contagem.setdefault(parte, [0, 0])
    contagem[parte][0] += 1
    if ok:
        contagem[parte][1] += 1
    else:
        falhas.append(f"[{parte}] {msg}")


def carrega(nome):
    return json.loads((CASOS / nome).read_text(encoding="utf-8"))


def fr(s):
    return None if s is None else Fraction(s)


# ------------------------------------------------------------------ 1. agendas
for c in carrega("agendas.json")["casos"]:
    a = lp.agenda(c["rec"])
    for campo in ("por_dia", "por_semana", "por_mes"):
        if campo in c:
            confere("1 agendas", a[campo] == fr(c[campo]), f"caso {c['id']}: {campo} = {a[campo]}, esperado {c[campo]}")
    if "texto" in c:
        confere("1 agendas", a["texto"] == c["texto"], f"caso {c['id']}: texto '{a['texto']}' ≠ '{c['texto']}'")
    if "horarios" in c:
        confere("1 agendas", a["horarios"] == c["horarios"], f"caso {c['id']}: horários {a['horarios']} ≠ {c['horarios']}")
    if "observacao_contem" in c:
        confere("1 agendas", any(c["observacao_contem"] in o for o in a["observacoes"]),
                f"caso {c['id']}: faltou observação com '{c['observacao_contem']}' ({a['observacoes']})")


# ------------------------------------------------------------------ 2. expressões
for k, c in enumerate(carrega("expressoes.json")["casos"], 1):
    fluxo = {"actions": {"X": {"type": "Compose", "inputs": 1, "runAfter": {}},
                         "Y": {"type": "Compose", "inputs": 2, "runAfter": {}},
                         "Loop": {"type": "Foreach", "foreach": "@body('X')", "runAfter": {"X": ["Succeeded"]},
                                  "actions": {"Teste": {"type": "Compose", "inputs": c["entrada"], "runAfter": {}}}}}}
    info = lp.ler(fluxo)
    usa = next(x["usa"] for x in info["acoes"] if x["nome"] == "Teste")
    confere("2 expressões", usa == sorted(c["usa"]), f"caso {k} {c['entrada']!r}: leu {usa}, esperado {sorted(c['usa'])}")


# ------------------------------------------------------------------ 3. gatilhos
for c in carrega("gatilhos.json")["casos"]:
    g = lp.ler({"triggers": {c["nome"]: c["gatilho"]}, "actions": {}})["gatilho"]
    ag = g.get("agenda")
    confere("3 gatilhos", g["tipo"] == c["tipo"], f"{c['nome']}: tipo {g['tipo']}")
    confere("3 gatilhos", g["conector"] == c["conector"], f"{c['nome']}: conector {g['conector']} ≠ {c['conector']}")
    confere("3 gatilhos", (ag["por_dia"] if ag else None) == fr(c["por_dia"]),
            f"{c['nome']}: por_dia {(ag or {}).get('por_dia')} ≠ {c['por_dia']}")
    for t in c["texto_contem"]:
        confere("3 gatilhos", t in g["texto"], f"{c['nome']}: texto '{g['texto']}' sem '{t}'")
    for campo in ("operacao", "condicoes", "concorrencia"):
        if campo in c:
            confere("3 gatilhos", g[campo] == c[campo], f"{c['nome']}: {campo} = {g[campo]!r}, esperado {c[campo]!r}")


# ------------------------------------------------------------------ 4. fluxos com gabarito escrito à mão
alvos = [(f"4 {a.name.replace('.esperado.json', '')}", CASOS / a.name.replace(".esperado.json", ".json"), a)
         for a in sorted(CASOS.glob("fluxo_*.esperado.json"))]
REAL = ROOT / "logicapps" / "reais" / "la-precos-logicapps.json"
if REAL.exists():  # 10. o JSON que voltou do Azure tem que ser lido igual ao gabarito escrito à mão
    alvos.append(("10 Logic App real (Azure)", REAL, CASOS / "fluxo_la_precos.esperado.json"))
for parte, json_fluxo, arq in alvos:
    esp = json.loads(arq.read_text(encoding="utf-8"))
    info = lp.ler(json.loads(json_fluxo.read_text(encoding="utf-8-sig")))
    g, eg = info["gatilho"], esp["gatilho"]
    for campo in ("nome", "tipo", "conector", "operacao", "dividir_em", "usa", "campos_entrada"):
        if campo in eg:
            confere(parte, g.get(campo) == eg[campo], f"gatilho.{campo} = {g.get(campo)!r}, esperado {eg[campo]!r}")
    confere(parte, ((g.get("agenda") or {}).get("por_dia")) == fr(eg["por_dia"]), f"gatilho por_dia {g.get('agenda')}")
    for t in eg["texto_contem"]:
        confere(parte, t in g["texto"], f"texto do gatilho sem '{t}'")
    lida = [[x["numero"], x["nome"], x["tipo"], x["pai"], x["ramo"]] for x in info["acoes"]]
    confere(parte, len(lida) == len(esp["ordem"]), f"{len(lida)} ações lidas, esperadas {len(esp['ordem'])}")
    for a, e in zip(lida, esp["ordem"], strict=False):  # o tamanho já foi conferido acima
        confere(parte, a == e, f"ordem/estrutura: leu {a}, esperado {e}")
    por = {x["nome"]: x for x in info["acoes"]}
    for n, refs in esp["usa"].items():
        confere(parte, por[n]["usa"] == sorted(refs), f"{n} usa {por[n]['usa']}, esperado {sorted(refs)}")
    for n, x in por.items():
        confere(parte, x["paralelo_com"] == sorted(esp["paralelo"].get(n, [])), f"{n} paralelo {x['paralelo_com']}")
    confere(parte, set(info["variaveis"]) == set(esp["variaveis"]), f"variáveis {set(info['variaveis'])}")
    for v, ev in esp["variaveis"].items():
        lv = info["variaveis"].get(v, {})
        for campo, valor in ev.items():
            confere(parte, lv.get(campo) == valor, f"variável {v}.{campo} = {lv.get(campo)!r}, esperado {valor!r}")
    confere(parte, info["conectores"] == esp["conectores"], f"conectores {info['conectores']}")
    confere(parte, info["trata_erro"] == esp["trata_erro"], f"trata_erro {info['trata_erro']}")
    lidos = sorted((r, onde) for r, onde, _ in info["achados"])
    esperados = sorted(tuple(a) for a in esp["achados"])
    for a in sorted(set(esperados) - set(lidos)):
        confere(parte, False, f"faltou achado {a}")
    for a in sorted(set(lidos) - set(esperados)):
        confere(parte, False, f"achado a mais (falso alarme) {a}")
    confere(parte, lidos == esperados, f"achados: {len(lidos)} lidos, {len(esperados)} esperados")
    c, ec = info["cobranca"], esp["cobranca"]
    for campo, valor in ec.items():
        lido = c.get(campo)
        valor = fr(valor) if campo == "execucoes_por_mes" else valor
        confere(parte, lido == valor, f"cobrança.{campo} = {lido!r}, esperado {valor!r}")
    for n, campos in esp["detalhes"].items():
        for campo, valor in campos.items():
            confere(parte, por[n]["detalhes"].get(campo) == valor,
                    f"{n}.detalhes.{campo} = {por[n]['detalhes'].get(campo)!r}, esperado {valor!r}")


# ------------------------------------------------------------------ 5. exemplos oficiais da Microsoft
def conta_acoes(acts):
    tot = 0
    for a in (acts or {}).values():
        tot += 1
        for _, filhos in lp.blocos(a):
            tot += conta_acoes(filhos)
    return tot


TIPOS_OFICIAIS = {"Recurrence", "Request", "Http", "HttpWebhook", "ApiConnection", "ApiConnectionWebhook", "Compose",
                  "Function", "Join", "ParseJson", "Query", "Response", "Select", "Table", "Terminate", "Wait",
                  "Workflow", "JavaScriptCode", "Foreach", "If", "Scope", "Switch", "Until"}
for ex in carrega("exemplos_oficiais.json")["exemplos"]:
    t = ex["definicao"]["type"]
    if t not in TIPOS_OFICIAIS:
        continue
    rot = f"linha {ex['linha_na_pagina']} ({ex['secao']})"
    try:
        if ex["eh_gatilho"]:
            info = lp.ler({"triggers": {ex["nome"]: ex["definicao"]}, "actions": {}})
            confere("5 exemplos oficiais", info["gatilho"]["tipo"] == t, f"{rot}: tipo do gatilho")
            confere("5 exemplos oficiais", bool(info["gatilho"]["texto"]), f"{rot}: gatilho sem descrição")
        else:
            defin = dict(ex["definicao"])
            defin["runAfter"] = {}  # o exemplo isolado não tem as ações anteriores
            info = lp.ler({"actions": {ex["nome"]: defin}})
            confere("5 exemplos oficiais", len(info["acoes"]) == conta_acoes({ex["nome"]: defin}),
                    f"{rot}: {len(info['acoes'])} ações lidas")
            confere("5 exemplos oficiais", info["acoes"][0]["tipo"] == t, f"{rot}: tipo lido {info['acoes'][0]['tipo']}")
            doc = dl.documento({**info, "nome": ex["nome"], "arquivo": "exemplo.json"})
            confere("5 exemplos oficiais", all(f"{x['numero']}. {x['nome']} —" in doc for x in info["acoes"]),
                    f"{rot}: ação faltando na documentação")
    except Exception as e:  # noqa: BLE001
        confere("5 exemplos oficiais", False, f"{rot}: ERRO {type(e).__name__}: {e}")


# ------------------------------------------------------------------ 6. exemplos do projeto
gab = json.loads((ROOT / "logicapps" / "achados_esperados.json").read_text(encoding="utf-8"))
for arq in sorted((ROOT / "logicapps" / "exemplos").glob("*.json")):
    info = lp.ler(json.loads(arq.read_text(encoding="utf-8")))
    lidos = sorted(r for r, _, _ in info["achados"])
    esperados = sorted(g["regra"] for g in gab if g["logicapp"] == arq.stem)
    confere("6 exemplos do projeto", lidos == esperados, f"{arq.stem}: achados {lidos}, esperado {esperados}")


# ------------------------------------------------------------------ 7. fluxos aleatórios com resposta conhecida
STATUS = [["Succeeded"]] * 6 + [["Failed"], ["Succeeded", "Failed"], ["TimedOut"], ["Failed", "Skipped", "TimedOut"]]
PALAVRAS = ["Ler", "Gravar", "Enviar", "Calcular", "Filtrar", "Montar", "Checar", "Buscar", "Avisar", "Somar"]


def gera_fluxo(rnd):
    verdade, criadas = {}, []
    params = {"p_url": {"type": "String", "defaultValue": "https://exemplo.com"},
              "p_email": {"type": "String", "defaultValue": "time@exemplo.com"}}
    variaveis = []
    cont = [0]

    def nome():
        cont[0] += 1
        return f"{rnd.choice(PALAVRAS)}_{cont[0]}"

    def expr_ref(foreachs, usa):
        """Escolhe uma referência válida e devolve (texto da expressão, referência esperada)."""
        opcoes = ["gatilho", "param"] + (["acao"] * 3 if criadas else []) + (["var"] if variaveis else []) + \
            (["item", "items"] if foreachs else [])
        o = rnd.choice(opcoes)
        if o == "gatilho":
            usa.add("gatilho")
            return rnd.choice(["triggerBody()?['id']", "triggerOutputs()"])
        if o == "param":
            p = rnd.choice(list(params))
            usa.add(f"parametro:{p}")
            return f"parameters('{p}')"
        if o == "acao":
            a = rnd.choice(criadas)
            usa.add(f"acao:{a}")
            return rnd.choice([f"body('{a}')", f"outputs('{a}')?['body']", f"actions('{a}').status"])
        if o == "var":
            v = rnd.choice(variaveis)
            usa.add(f"variavel:{v}")
            return f"variables('{v}')"
        if o == "item":
            usa.add(f"item:{foreachs[-1]}")
            return "item()?['campo']"
        f = rnd.choice(foreachs)
        usa.add(f"item:{f}")
        return f"items('{f}')"

    def texto(foreachs, usa, n=None):
        partes = ["valor fixo"]
        for _ in range(rnd.randint(0, 3) if n is None else n):
            partes.append("@{" + expr_ref(foreachs, usa) + "}")
        rnd.shuffle(partes)
        return " ".join(partes)

    def bloco(pai, ramo, nivel, foreachs, loops):
        nomes_b = [nome() for _ in range(rnd.randint(1, 4 if nivel < 2 else 2))]
        acts = {}
        for i, n in enumerate(nomes_b):
            deps = rnd.sample(nomes_b[:i], k=min(i, rnd.choice([1, 1, 1, 2]))) if i else []
            ra = {d: list(rnd.choice(STATUS)) for d in deps}
            usa = set()
            tipos = ["Compose", "Http", "ApiConnection"] + (["Foreach", "If", "Scope", "Switch", "Until"] if nivel < 3 else [])
            t = rnd.choice(tipos)
            a = {"type": t, "runAfter": ra}
            filhos = []
            if t == "Compose":
                a["inputs"] = texto(foreachs, usa) if rnd.random() < 0.5 else {"campo": texto(foreachs, usa), "n": 1}
                if isinstance(a["inputs"], str) and not usa:
                    a["inputs"] = "@{" + expr_ref(foreachs, usa) + "}"
            elif t == "Http":
                a["inputs"] = {"method": rnd.choice(["GET", "POST"]), "uri": "https://api.exemplo.com/" + texto(foreachs, usa, 1)}
            elif t == "ApiConnection":
                a["inputs"] = {"host": {"connection": {"name": "@parameters('$connections')['office365']['connectionId']"}},
                               "method": "post", "path": "/v2/Mail",
                               "body": {"To": "@{parameters('p_email')}", "Subject": "Aviso", "Body": texto(foreachs, usa, 1)}}
                usa.add("parametro:p_email")
            elif t == "Foreach":
                a["foreach"] = "@" + expr_ref(foreachs, usa)
                if rnd.random() < 0.3:
                    a["runtimeConfiguration"] = {"concurrency": {"repetitions": 1}}
                filhos = [(None, foreachs + [n], loops + [n])]
            elif t == "Until":
                a["expression"] = "@equals(" + expr_ref(foreachs, usa) + ", 1)"
                a["limit"] = {"count": rnd.randint(1, 60), "timeout": "PT1H"}
                filhos = [(None, foreachs, loops + [n])]
            elif t == "Scope":
                filhos = [(None, foreachs, loops)]
            elif t == "If":
                a["expression"] = {"and": [{"equals": ["@" + expr_ref(foreachs, usa), "sim"]}]}
                filhos = [("Sim", foreachs, loops), ("Não", foreachs, loops)]
            elif t == "Switch":
                a["expression"] = "@" + expr_ref(foreachs, usa)
                casos = [f"Caso_{k}" for k in range(1, rnd.randint(1, 3) + 1)]
                filhos = [(c, foreachs, loops) for c in casos] + ([("Padrão", foreachs, loops)] if rnd.random() < 0.6 else [])
            verdade[n] = {"tipo": t, "pai": pai, "ramo": ramo, "nivel": nivel, "usa": sorted(usa), "run_after": ra}
            criadas.append(n)
            for r, fe, lo in filhos:
                sub = bloco(n, r, nivel + 1, fe, lo)
                if t in ("Foreach", "Until", "Scope"):
                    a["actions"] = sub
                elif t == "If":
                    if r == "Sim":
                        a["actions"] = sub
                    else:
                        a["else"] = {"actions": sub}
                elif r == "Padrão":
                    a["default"] = {"actions": sub}
                else:
                    a.setdefault("cases", {})[r] = {"case": r.lower(), "actions": sub}
            acts[n] = a
        itens = list(acts.items())
        rnd.shuffle(itens)  # a ordem no arquivo não pode mudar a leitura
        return dict(itens)

    topo = {}
    for k in range(rnd.randint(0, 2)):
        v = f"var_{k}"
        n = f"Inicializar_{v}"
        topo[n] = {"type": "InitializeVariable", "inputs": {"variables": [{"name": v, "type": "string", "value": ""}]},
                   "runAfter": {}}
        verdade[n] = {"tipo": "InitializeVariable", "pai": None, "ramo": None, "nivel": 0, "usa": [], "run_after": {}}
        variaveis.append(v)
        criadas.append(n)
    topo.update(bloco(None, None, 0, [], []))
    fluxo = {"parameters": {"$connections": {"type": "Object", "defaultValue": {}}, **params},
             "triggers": {"Gatilho": {"type": "Recurrence", "recurrence": {"frequency": "Hour", "interval": rnd.randint(1, 12)}}},
             "actions": topo}
    return fluxo, verdade


def confere_estrutura(parte, fluxo, verdade, semente):
    info = lp.ler(fluxo)
    por = {x["nome"]: x for x in info["acoes"]}
    pos = {x["nome"]: k for k, x in enumerate(info["acoes"])}
    ok = set(por) == set(verdade)
    confere(parte, ok, f"semente {semente}: ações lidas ≠ ações do fluxo")
    if not ok:
        return info
    for n, v in verdade.items():
        x = por[n]
        for campo, lido in (("tipo", x["tipo"]), ("pai", x["pai"]), ("ramo", x["ramo"]), ("nivel", x["nivel"]),
                            ("usa", x["usa"]), ("run_after", x["run_after"])):
            confere(parte, lido == v[campo], f"semente {semente}: {n}.{campo} = {lido!r}, esperado {v[campo]!r}")
        if v["pai"]:
            confere(parte, pos[v["pai"]] < pos[n], f"semente {semente}: {n} aparece antes do bloco {v['pai']}")
        for d in v["run_after"]:
            confere(parte, pos[d] < pos[n], f"semente {semente}: {n} aparece antes de {d}, de quem depende")
    confere(parte, len({x["numero"] for x in info["acoes"]}) == len(info["acoes"]), f"semente {semente}: numeração repetida")
    confere(parte, not [p for p in info["problemas"]], f"semente {semente}: problema falso {info['problemas'][:2]}")
    return info


N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
total_acoes = 0
for semente in range(N):
    rnd = random.Random(semente)
    fluxo, verdade = gera_fluxo(rnd)
    total_acoes += len(verdade)
    info = confere_estrutura("7 aleatório", fluxo, verdade, semente)

    # ---------------------------------------------------------------- 8. mutação: estraga e confere se percebe
    if semente % 4 == 0:
        alvo = rnd.choice(list(verdade))
        fluxo = json.loads(json.dumps(fluxo))  # cópia: a mutação não pode alterar o fluxo já lido
        ac = fluxo["actions"]

        def acha(acts, n):
            if n in acts:
                return acts[n]
            for a in acts.values():
                for _, f in lp.blocos(a):
                    r = acha(f, n)
                    if r:
                        return r
            return None
        defin = acha(ac, alvo)
        tipo_mut = semente % 3
        if tipo_mut == 0:
            defin["inputs"] = "@{body('Acao_que_nao_existe')}" if defin["type"] == "Compose" else defin.get("inputs")
            esperado = ("REFERENCIA_INEXISTENTE", alvo) if defin["type"] == "Compose" else None
        elif tipo_mut == 1:
            defin.setdefault("runAfter", {})["Acao_fantasma"] = ["Succeeded"]
            esperado = ("RUNAFTER_INVALIDO", alvo)
        else:
            defin["inputs"] = {"method": "GET", "uri": "https://x.exemplo.com/api?code=SEGREDO123"}
            defin["type"] = "Http"
            for k in ("actions", "else", "cases", "default", "foreach", "expression", "limit", "runtimeConfiguration"):
                defin.pop(k, None)
            esperado = ("SEGREDO_NA_URL", alvo)
        if esperado:
            info2 = lp.ler(fluxo)
            achou = {(r, o) for r, o, _ in info2["achados"]}
            confere("8 mutação", esperado in achou, f"semente {semente}: não percebeu {esperado}")
            if esperado[0] == "SEGREDO_NA_URL":
                doc = dl.documento({**info2, "nome": "mutado", "arquivo": "mutado.json"})
                confere("9 documentação", "SEGREDO123" not in doc, f"semente {semente}: segredo vazou na documentação")

    # ---------------------------------------------------------------- 9. documentação dos fluxos aleatórios
    if semente % 10 == 0:
        doc = dl.documento({**info, "nome": f"aleatorio_{semente}", "arquivo": "aleatorio.json"})
        passos = re.findall(r"^#{3,6} (\S+)\. (\S+) — ", doc, re.M)
        confere("9 documentação", sorted(n for _, n in passos) == sorted(verdade),
                f"semente {semente}: passo a passo não bate com as ações")
        bloco_merm = doc.split("```mermaid", 1)[1].split("```", 1)[0]
        confere("9 documentação", all(f"{x['numero']}. " in bloco_merm for x in info["acoes"]),
                f"semente {semente}: ação faltando no diagrama")
        tabela = doc.split("## Ações\n", 1)[1].split("\n## ", 1)[0]
        confere("9 documentação", sum(1 for l in tabela.splitlines() if l.startswith("| ") and "---" not in l) - 1
                == len(verdade), f"semente {semente}: tabela de ações com tamanho errado")


# ------------------------------------------------------------------ 9. documentação dos casos fixos
for nome in ("fluxo_completo", "fluxo_com_problemas"):
    info = lp.ler(json.loads((CASOS / f"{nome}.json").read_text(encoding="utf-8")))
    doc = dl.documento({**info, "nome": nome, "arquivo": f"{nome}.json"})
    for x in info["acoes"]:
        confere("9 documentação", f"{x['numero']}. {x['nome']} —" in doc, f"{nome}: falta {x['nome']} no passo a passo")
    for segredo in ("abc123", "sig=abc"):
        confere("9 documentação", segredo not in doc, f"{nome}: segredo '{segredo}' vazou na documentação")

# ------------------------------------------------------------------ resultado
print("Bateria de testes do leitor de Logic Apps\n")
for parte in sorted(contagem, key=lambda p: (int(p.split()[0]), p)):
    tot, ok = contagem[parte]
    print(f"  {'OK  ' if ok == tot else 'FALHOU'} {parte:<28} {ok}/{tot} verificações")
print(f"\n  Fluxos aleatórios: {N} ({total_acoes} ações geradas)")
for f in falhas[:40]:
    print("  -", f)
if len(falhas) > 40:
    print(f"  ... e mais {len(falhas) - 40} falha(s)")
tot = sum(c[0] for c in contagem.values())
ok = sum(c[1] for c in contagem.values())
print(f"\nRESULTADO: {'LEITURA 100% CORRETA' if not falhas else 'COM FALHAS'} — {ok}/{tot} verificações ({100 * ok / tot:.2f}%)")
sys.exit(0 if not falhas else 1)
