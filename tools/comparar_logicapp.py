"""Compara duas versões de uma Logic App: o que mudou no fluxo, no custo previsto e nos riscos.

Tudo é calculado em código, pelo mesmo leitor da documentação (tools/logicapp_parser.py):
  - gatilho e agenda (execuções por mês);
  - ações novas, removidas e alteradas (entradas, ordem/runAfter, tipo, retentativa, lugar no fluxo);
  - conectores novos e removidos;
  - ações cobradas por execução e por mês, e o custo/mês em R$ quando há preços oficiais sincronizados;
  - achados de boas práticas que apareceram e que foram resolvidos;
  - pontos de atenção (o que merece revisão antes de publicar).

Uso:
  python tools/comparar_logicapp.py antes.json depois.json      compara dois arquivos (definição ou ARM/exportação)
  python tools/comparar_logicapp.py anterior <nome>             versão guardada em logicapps/versoes/ × a atual
                                                                (sem nome, lê a variável de ambiente 'nome': usado pelo agente)
  python tools/comparar_logicapp.py exemplo                     o mesmo para a lgc-desvios-processo (fictícia)
  python tools/comparar_logicapp.py azure                       as 2 últimas versões da Logic App real (só leitura, az login)
  Opções: --saida arquivo.md (padrão: docs/comparacoes/<nome>.md) · --nome <nome da Logic App>
Termina com "RESULTADO: COMPARAÇÃO GERADA".
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doc_logicapp as dl  # noqa: E402
import logicapp_parser as lp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VERSOES = ROOT / "logicapps" / "versoes"
SAIDA = ROOT / "docs" / "comparacoes"
LIMITE_CUSTO = 0.20  # aumento de execuções/ações por mês acima disso vira ponto de atenção


def carregar(caminho):
    d = json.loads(Path(caminho).read_text(encoding="utf-8-sig"))
    props = d.get("properties", {}) if isinstance(d.get("properties"), dict) else {}
    definicao = props.get("definition") or d.get("definition") or d
    meta = {"versao": props.get("version") or d.get("version"), "alterada_em": props.get("changedTime") or d.get("changedTime")}
    return definicao, meta


def vazia(definicao):
    return not (definicao.get("triggers") or definicao.get("actions"))


def _impressao(acao):
    """Identidade do conteúdo de uma ação, sem runAfter, sem retentativa (comparada à parte) e sem as ações
    internas de loops e condições (comparadas uma a uma)."""
    a = {k: v for k, v in acao.items() if k not in ("runAfter", "actions", "else", "cases", "default", "retryPolicy")}
    if isinstance(a.get("inputs"), dict):
        a["inputs"] = {k: v for k, v in a["inputs"].items() if k != "retryPolicy"}
    return hashlib.sha256(json.dumps(a, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _lugar(x):
    return (x["pai"], x["ramo"])


def _f(v):
    return None if v is None else float(v)


def comparar(def_antes, def_depois):
    a, b = lp.ler(def_antes), lp.ler(def_depois)
    acoes_a, acoes_b = {x["nome"]: x for x in a["acoes"]}, {x["nome"]: x for x in b["acoes"]}
    novas = [acoes_b[n] for n in acoes_b if n not in acoes_a]
    removidas = [acoes_a[n] for n in acoes_a if n not in acoes_b]
    alteradas = []
    for n in acoes_a.keys() & acoes_b.keys():
        x, y, mud = acoes_a[n], acoes_b[n], []
        if x["tipo"] != y["tipo"]:
            mud.append(f"tipo: {dl.TIPO_PT.get(x['tipo'], x['tipo'])} → {dl.TIPO_PT.get(y['tipo'], y['tipo'])}")
        if x["run_after"] != y["run_after"]:
            fmt = lambda r: "; ".join(f"{d} ({', '.join(s)})" for d, s in r.items()) or "início do bloco"  # noqa: E731
            mud.append(f"executa após: {fmt(x['run_after'])} → {fmt(y['run_after'])}")
        if _lugar(x) != _lugar(y):
            mud.append(f"mudou de lugar: {x['pai'] or 'fluxo principal'} → {y['pai'] or 'fluxo principal'}")
        if x["retentativa"] != y["retentativa"]:
            mud.append(f"retentativa: {x['retentativa']['tipo']} → {y['retentativa']['tipo']}")
        if _impressao(x["acao"]) != _impressao(y["acao"]) and not any(m.startswith("tipo") for m in mud):
            mud.append("entradas/configuração alteradas")
        if mud:
            alteradas.append({"nome": n, "numero": y["numero"], "mudancas": mud})
    alteradas.sort(key=lambda z: z["numero"])

    def gat(i):
        g = i["gatilho"]
        return {"nome": g["nome"], "tipo": g["tipo"], "texto": g["texto"]} if g else None

    ca, cb = a["cobranca"], b["cobranca"]
    cobranca = {"execucoes_mes": (_f(ca.get("execucoes_por_mes")), _f(cb.get("execucoes_por_mes"))),
                "fixas_por_execucao": (ca["fixas_por_execucao"], cb["fixas_por_execucao"]),
                "acoes_fixas_mes": (_f(ca.get("acoes_fixas_por_mes")), _f(cb.get("acoes_fixas_por_mes"))),
                "por_item": (ca["por_item_de_loop"], cb["por_item_de_loop"])}
    custo = [dl.custo_mes(i) for i in (a, b)]
    custo = tuple(c["custo"] if c and "erro" not in c else None for c in custo)

    ach_a, ach_b = {(c, alvo): det for c, alvo, det in a["achados"]}, {(c, alvo): det for c, alvo, det in b["achados"]}
    achados_novos = [(c, alvo, ach_b[(c, alvo)]) for (c, alvo) in ach_b if (c, alvo) not in ach_a]
    achados_resolvidos = [(c, alvo, ach_a[(c, alvo)]) for (c, alvo) in ach_a if (c, alvo) not in ach_b]
    sev = lambda c: lp.REGRAS.get(c, ("Média",))[0]  # noqa: E731
    achados_novos.sort(key=lambda z: (lp.ORDEM_SEV.get(sev(z[0]), 9), z[0]))
    achados_resolvidos.sort(key=lambda z: (lp.ORDEM_SEV.get(sev(z[0]), 9), z[0]))

    atencao = []
    ea, eb = cobranca["acoes_fixas_mes"]
    if ea and eb and eb > ea * (1 + LIMITE_CUSTO):
        atencao.append(f"Ações cobradas por mês sobem {(eb / ea - 1) * 100:.0f}% ({dl.num(ea)} → {dl.num(eb)}): "
                       "confirmar se a mudança foi intencional.")
    if custo[0] is not None and custo[1] is not None and custo[1] > custo[0] * (1 + LIMITE_CUSTO) and custo[1] > 0.01:
        atencao.append(f"Custo estimado por mês sobe de R$ {dl.br(custo[0], 2)} para R$ {dl.br(custo[1], 2)}.")
    for c, alvo, det in achados_novos:
        if sev(c) in ("Alta", "Média"):
            atencao.append(f"Risco novo ({sev(c)}): {c} em `{alvo}` ({det}).")
    if a["trata_erro"] and not b["trata_erro"]:
        atencao.append("A versão nova não tem mais tratamento de erro (nenhuma ação roda após falha).")
    for n in sorted(set(b["conectores"]) - set(a["conectores"])):
        atencao.append(f"Conector novo: {dl.con_pt(n)} (precisa de conexão autorizada no ambiente de destino).")

    return {"gatilho": (gat(a), gat(b)), "novas": novas, "removidas": removidas, "alteradas": alteradas,
            "conectores": (sorted(set(b["conectores"]) - set(a["conectores"])), sorted(set(a["conectores"]) - set(b["conectores"]))),
            "cobranca": cobranca, "custo_mes": custo, "achados_novos": achados_novos,
            "achados_resolvidos": achados_resolvidos, "atencao": atencao, "trata_erro": (a["trata_erro"], b["trata_erro"]),
            "total_acoes": (len(a["acoes"]), len(b["acoes"]))}


def _n(v):
    return "–" if v is None else dl.num(v)


def relatorio(nome, r, meta_a=None, meta_b=None, origem=""):
    meta_a, meta_b = meta_a or {}, meta_b or {}
    ga, gb = r["gatilho"]
    sem_mudanca = not (r["novas"] or r["removidas"] or r["alteradas"] or ga != gb or any(r["conectores"]))
    L = [f"# Comparação de versões: {nome}", "",
         f"> Gerado automaticamente em código (tools/comparar_logicapp.py), sem IA. {origem}".rstrip(), ""]
    if meta_a.get("versao") or meta_b.get("versao"):
        L += ["| | Antes | Depois |", "|---|---|---|",
              f"| Versão | {meta_a.get('versao') or '–'} | {meta_b.get('versao') or 'atual'} |",
              f"| Alterada em | {(meta_a.get('alterada_em') or '–')[:19].replace('T', ' ')} | "
              f"{(meta_b.get('alterada_em') or '–')[:19].replace('T', ' ')} |", ""]
    L += ["## Resumo", ""]
    if sem_mudanca:
        L.append("- Nenhuma mudança no fluxo entre as duas versões.")
    else:
        L.append(f"- Ações: {r['total_acoes'][0]} → {r['total_acoes'][1]} ({len(r['novas'])} nova(s), "
                 f"{len(r['removidas'])} removida(s), {len(r['alteradas'])} alterada(s)).")
        if ga != gb:
            L.append(f"- Gatilho: {ga['texto'] if ga else '–'} → **{gb['texto'] if gb else '–'}**.")
    ea, eb = r["cobranca"]["execucoes_mes"]
    if ea != eb:
        L.append(f"- Execuções por mês: {_n(ea)} → **{_n(eb)}**.")
    L.append(f"- Riscos: {len(r['achados_novos'])} novo(s), {len(r['achados_resolvidos'])} resolvido(s).")
    L += ["", "## Pontos de atenção", ""]
    L += [f"- {x}" for x in r["atencao"]] or ["- Nenhum."]

    L += ["", "## Custo previsto", "", "| Item | Antes | Depois |", "|---|---|---|"]
    c = r["cobranca"]
    L.append(f"| Execuções do gatilho por mês | {_n(c['execucoes_mes'][0])} | {_n(c['execucoes_mes'][1])} |")
    L.append(f"| Ações cobradas por execução (fora de loops) | {c['fixas_por_execucao'][0]} | {c['fixas_por_execucao'][1]} |")
    L.append(f"| Ações fixas por mês | {_n(c['acoes_fixas_mes'][0])} | {_n(c['acoes_fixas_mes'][1])} |")
    for loop in sorted(set(c["por_item"][0]) | set(c["por_item"][1])):
        L.append(f"| Ações a cada item de `{loop}` | {c['por_item'][0].get(loop, '–')} | {c['por_item'][1].get(loop, '–')} |")
    ca, cb = r["custo_mes"]
    if ca is not None or cb is not None:
        L.append(f"| Custo estimado por mês (preços oficiais sincronizados) | "
                 f"{'–' if ca is None else 'R$ ' + dl.br(ca, 2)} | {'–' if cb is None else 'R$ ' + dl.br(cb, 2)} |")

    L += ["", "## Ações", ""]
    if r["novas"]:
        L += ["**Novas**", "", "| # | Ação | Tipo | O que faz |", "|---|---|---|---|"]
        L += [f"| {x['numero']} | `{x['nome']}` | {dl.TIPO_PT.get(x['tipo'], x['tipo'])} | {dl.curto(dl.o_que_faz(x), 160)} |"
              for x in r["novas"]]
        L.append("")
    if r["removidas"]:
        L += ["**Removidas**", "", "| Ação | Tipo |", "|---|---|"]
        L += [f"| `{x['nome']}` | {dl.TIPO_PT.get(x['tipo'], x['tipo'])} |" for x in r["removidas"]]
        L.append("")
    if r["alteradas"]:
        L += ["**Alteradas**", "", "| # | Ação | O que mudou |", "|---|---|---|"]
        L += [f"| {x['numero']} | `{x['nome']}` | {dl.curto('; '.join(x['mudancas']), 220)} |" for x in r["alteradas"]]
        L.append("")
    if not (r["novas"] or r["removidas"] or r["alteradas"]):
        L += ["Nenhuma ação mudou.", ""]
    novos_c, sairam_c = r["conectores"]
    if novos_c or sairam_c:
        L += ["## Conectores", ""]
        L += [f"- Novo: {dl.con_pt(x)}" for x in novos_c] + [f"- Removido: {dl.con_pt(x)}" for x in sairam_c] + [""]

    L += ["## Riscos de boas práticas", ""]
    if r["achados_novos"]:
        L += ["**Apareceram**", "", "| Severidade | Achado | Onde | Recomendação |", "|---|---|---|---|"]
        for cod, alvo, det in r["achados_novos"]:
            sev, _, _, rec = (*lp.REGRAS.get(cod, ("Média", "", "", "")),)
            L.append(f"| {sev} | {cod} ({dl.curto(det, 80)}) | `{alvo}` | {rec} |")
        L.append("")
    if r["achados_resolvidos"]:
        L += ["**Resolvidos**", "", "| Achado | Onde |", "|---|---|"]
        L += [f"| {cod} | `{alvo}` |" for cod, alvo, _ in r["achados_resolvidos"]] + [""]
    if not (r["achados_novos"] or r["achados_resolvidos"]):
        L += ["Nenhum risco novo nem resolvido.", ""]
    L += ["## Fontes oficiais", "",
          "- [Workflow Definition Language](https://learn.microsoft.com/azure/logic-apps/workflow-definition-language-schema)",
          "- [Cobrança das Logic Apps (Consumo)](https://learn.microsoft.com/azure/logic-apps/logic-apps-pricing)",
          "- [Versões de uma Logic App (REST)](https://learn.microsoft.com/rest/api/logic/workflow-versions/list)"]
    return "\n".join(L) + "\n"


def gravar(nome, texto, saida=None):
    destino = Path(saida) if saida else SAIDA / f"{nome}.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    return destino


def imprime_resumo(nome, r, destino):
    print(f"Comparação de {nome}: ações {r['total_acoes'][0]} → {r['total_acoes'][1]} "
          f"({len(r['novas'])} nova(s), {len(r['removidas'])} removida(s), {len(r['alteradas'])} alterada(s))")
    ga, gb = r["gatilho"]
    if ga != gb:
        print(f"  gatilho: {ga['texto'] if ga else '–'} → {gb['texto'] if gb else '–'}")
    ea, eb = r["cobranca"]["execucoes_mes"]
    if ea != eb:
        print(f"  execuções por mês: {_n(ea)} → {_n(eb)}")
    for rot, chave in (("nova", "novas"), ("removida", "removidas")):
        for x in r[chave]:
            print(f"  ação {rot}: {x['nome']} ({dl.TIPO_PT.get(x['tipo'], x['tipo'])})")
    for x in r["alteradas"]:
        print(f"  ação alterada: {x['nome']}: {'; '.join(x['mudancas'])}")
    for cod, alvo, det in r["achados_novos"]:
        print(f"  risco novo: {cod} em {alvo} ({det})")
    for cod, alvo, _ in r["achados_resolvidos"]:
        print(f"  risco resolvido: {cod} em {alvo}")
    for x in r["atencao"]:
        print(f"  ATENÇÃO: {x}")
    try:
        mostrar = destino.relative_to(ROOT)
    except ValueError:
        mostrar = destino
    print(f"Relatório: {mostrar}")
    print("RESULTADO: COMPARAÇÃO GERADA")


def main(argv):
    dl.utf8_stdout()
    saida = argv[argv.index("--saida") + 1] if "--saida" in argv else None
    nome = argv[argv.index("--nome") + 1] if "--nome" in argv else None
    pos = [x for i, x in enumerate(argv) if not x.startswith("--") and (i == 0 or argv[i - 1] not in ("--saida", "--nome"))]
    if pos[:1] in (["exemplo"], ["anterior"]):
        nome = "lgc-desvios-processo" if pos[0] == "exemplo" else (pos[1] if len(pos) > 1 else os.environ.get("nome", "")).strip()
        atuais = dl.arquivos()
        guardadas = sorted(VERSOES.glob(f"{nome}.*.json")) if nome else []
        if nome not in atuais or not guardadas:
            disponiveis = sorted({p.name.split(".")[0] for p in VERSOES.glob("*.json")})
            print(f"Não há versão anterior guardada de '{nome}'. Com versão anterior: {', '.join(disponiveis) or 'nenhuma'}.")
            print("RESULTADO: SEM VERSÃO ANTERIOR")
            return 0
        antes, depois = guardadas[-1], atuais[nome]
        origem = (f"Versão anterior: {antes.relative_to(ROOT).as_posix()}; atual: {depois.relative_to(ROOT).as_posix()}.")
        if nome == "lgc-desvios-processo":
            origem += " É a mudança por trás da anomalia A4 dos dados de custo (mudança de patamar desde 15/09)."
    elif pos[:1] == ["azure"]:
        import azure_logicapp as az
        try:
            versoes = az.versoes()
        except az.ErroAzure as e:
            print("ERRO:", e)
            print("RESULTADO: ERRO ao ler as versões no Azure")
            return 1
        # a primeira versão de uma Logic App costuma ser a criação, ainda vazia (sem gatilho nem ações): não é uma mudança
        com_conteudo = [v for v in versoes if not vazia(carregar(v)[0])]
        if len(com_conteudo) < 2:
            vazias = len(versoes) - len(com_conteudo)
            print(f"A Logic App tem {len(versoes)} versão(ões) no Azure, {len(com_conteudo)} com fluxo"
                  + (f" ({vazias} é a criação, ainda vazia)" if vazias else "") + ". Não há duas versões com fluxo para comparar.")
            print("Para ter o que comparar: mude algo no designer da Logic App, salve e rode de novo.")
            print("RESULTADO: SÓ UMA VERSÃO COM FLUXO")
            return 0
        antes, depois = com_conteudo[1], com_conteudo[0]
        nome = nome or az.cfg()["nome"]
        origem = "Versões baixadas do Azure (só leitura) para relatorios/azure/versoes/."
    elif len(pos) == 2:
        antes, depois = Path(pos[0]), Path(pos[1])
        faltam = [str(p) for p in (antes, depois) if not p.exists()]
        if faltam:
            print(f"Arquivo não encontrado: {', '.join(faltam)}. Passe o caminho de dois JSONs de Logic App "
                  "(definição ou exportação), ex.: logicapps/versoes/lgc-desvios-processo.v1.json")
            print("RESULTADO: ERRO arquivo não encontrado")
            return 1
        nome = nome or depois.stem
        origem = f"Antes: {antes.name} · depois: {depois.name}."
    else:
        print(__doc__)
        return 1
    da, ma = carregar(antes)
    db, mb = carregar(depois)
    r = comparar(da, db)
    destino = gravar(nome, relatorio(nome, r, ma, mb, origem), saida)
    imprime_resumo(nome, r, destino)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
