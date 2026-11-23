"""FinOps por tenant: quanto cada cliente gasta, se vai estourar o orçamento, quanto dá para economizar
e quanto já foi economizado. Tudo calculado em código (sem IA) e sempre separado por tenant.

Entradas (dados fictícios em data/tenants/, gerados por data/tenants/gerar_tenants.py; outra pasta por PILOTO_TENANTS_DIR):
  focus_tenants.csv  custo diário no formato FOCUS + x_TenantId (o mesmo formato da exportação FOCUS do Cost Management,
                     acrescido da coluna do tenant de onde a exportação veio)
  inventario.json    estado dos recursos como o Azure Resource Graph devolve + CPU P95 de 14 dias (Azure Monitor)
  tenants.json       tenants e orçamento mensal · acoes.json: ações de economia já implementadas

Regras (as mesmas do gabarito; os limites são do projeto e podem ser ajustados):
  custo do mês de um recurso = soma dos últimos 30 dias até a data de corte (último dia com dados)
  disco_orfao          disco gerenciado com diskState "Unattached" → economia = 100% do custo do mês
  ip_orfao             IP público sem ipConfiguration (não associado) → 100%
  snapshot_antigo      snapshot com mais de 90 dias → 100%
  vm_superdimensionada CPU P95 de 14 dias abaixo de 20% → 50% (um tamanho abaixo na mesma família, estimativa)
  previsão do mês      custo do mês até o corte + média diária dos últimos 7 dias × dias que faltam
  economia realizada   para cada ação implementada: (média diária dos 30 dias antes − média depois) × 30, medida nos dados
  cobertura de tags    % do custo do mês em recursos com as tags owner e centro_custo

Isolamento: toda conta filtra por x_TenantId; o relatório de um tenant nunca mostra recurso, nome ou valor de outro.

Uso:
  python tools/finops_tenants.py tenants                 visão consolidada (um tenant por linha)
  python tools/finops_tenants.py tenant <nome>           detalhe: showback, previsão × orçamento, oportunidades
  python tools/finops_tenants.py economia <nome>         oportunidades de economia com a evidência de cada uma
  python tools/finops_tenants.py executivo [<nome>]      relatório executivo de 1 página (sem nome: todos + consolidado)
  (sem <nome>, tenant/economia leem a variável de ambiente 'tenant': usado pelo agente)
Termina com "RESULTADO: ..." (OK, TENANT NÃO ENCONTRADO ou RELATÓRIOS EXECUTIVOS GERADOS).
"""
import csv
import json
import os
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASTA = Path(os.environ.get("PILOTO_TENANTS_DIR", ROOT / "data" / "tenants"))
SAIDA = ROOT / "relatorios" / "executivo"

DIAS_MES = 30
SNAPSHOT_VELHO_DIAS = 90
CPU_P95_LIMITE = 20.0
FATOR_RIGHTSIZING = 0.5
DIAS_TENDENCIA = 7
TIPOS = {"microsoft.compute/disks": "disco", "microsoft.network/publicipaddresses": "ip",
         "microsoft.compute/snapshots": "snapshot", "microsoft.compute/virtualmachines": "vm"}
NOME_OPORTUNIDADE = {
    "disco_orfao": "Disco sem VM (órfão)", "ip_orfao": "IP público sem uso", "snapshot_antigo": "Snapshot antigo",
    "vm_superdimensionada": "VM superdimensionada"}
ACAO = {"disco_orfao": "Excluir o disco (fazer um snapshot antes, se houver dúvida)",
        "ip_orfao": "Excluir o IP público não associado",
        "snapshot_antigo": "Excluir o snapshot ou mover para camada de arquivamento, conforme a política de retenção",
        "vm_superdimensionada": "Reduzir um tamanho na mesma família e acompanhar a CPU por 14 dias"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def br(v, casas=2):
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def rs(v):
    return f"R$ {br(v)}"


def _sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c)).lower().strip()


# ------------------------------------------------------------------ dados
def carregar():
    tenants = json.loads((PASTA / "tenants.json").read_text(encoding="utf-8"))
    inventario = json.loads((PASTA / "inventario.json").read_text(encoding="utf-8"))
    acoes = json.loads((PASTA / "acoes.json").read_text(encoding="utf-8")) if (PASTA / "acoes.json").exists() else []
    custos = defaultdict(lambda: defaultdict(float))  # (tenant, recurso) -> dia -> custo
    meta = {}
    with (PASTA / "focus_tenants.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            chave = (r["x_TenantId"], r["ResourceName"])
            dia = date.fromisoformat(r["ChargePeriodStart"][:10])
            custos[chave][dia] += float(r["EffectiveCost"])
            meta[chave] = {"tags": json.loads(r["Tags"] or "{}"), "tipo": r["x_ResourceType"], "rg": r["x_ResourceGroupName"],
                           "assinatura": r["SubAccountName"]}
    corte = max(d for s in custos.values() for d in s)
    return {"tenants": tenants, "inventario": inventario, "acoes": acoes, "custos": custos, "meta": meta, "corte": corte}


def achar_tenant(dados, texto):
    """Pelo id, pelo nome exato ou pela primeira palavra do nome (sem acento e sem maiúsculas)."""
    alvo = _sem_acento(texto)
    if not alvo:
        return None
    for t in dados["tenants"]:
        nome = _sem_acento(t["nome"])
        if alvo in (t["id"].lower(), nome, nome.split()[0]):
            return t
    return None


# ------------------------------------------------------------------ análise de um tenant
def analisar(dados, tenant):
    tid, corte = tenant["id"], dados["corte"]
    ult30 = {corte - timedelta(days=i) for i in range(DIAS_MES)}
    recursos = {nome: s for (t, nome), s in dados["custos"].items() if t == tid}
    meta = {nome: m for (t, nome), m in dados["meta"].items() if t == tid}

    def custo30(nome):
        return round(sum(v for d, v in recursos.get(nome, {}).items() if d in ult30), 2)

    custo_mes_rec = {n: custo30(n) for n in recursos}
    total30 = sum(custo_mes_rec.values())

    # previsão do mês corrente × orçamento
    ate_hoje = sum(v for s in recursos.values() for d, v in s.items() if (d.year, d.month) == (corte.year, corte.month))
    ult7 = {corte - timedelta(days=i) for i in range(DIAS_TENDENCIA)}
    media7 = sum(v for s in recursos.values() for d, v in s.items() if d in ult7) / DIAS_TENDENCIA
    fim_mes = (corte.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    previsao = ate_hoje + media7 * (fim_mes - corte).days
    orcamento = float(tenant.get("orcamento_mensal") or 0)

    # o que mais subiu: média dos últimos 7 dias × média do mês anterior (por recurso)
    inicio_mes = corte.replace(day=1)
    mes_ant = {inicio_mes - timedelta(days=i) for i in range(1, 31)}
    aumentos = []
    for n, s in recursos.items():
        antes = sum(v for d, v in s.items() if d in mes_ant) / 30
        agora = sum(v for d, v in s.items() if d in ult7) / DIAS_TENDENCIA
        if antes > 0 and agora > antes * 1.5:
            desde = min((d for d in sorted(s) if d >= inicio_mes and s[d] > antes * 1.5), default=None)
            aumentos.append({"recurso": n, "media_diaria_antes": round(antes, 2), "media_diaria_agora": round(agora, 2),
                             "aumento_pct": round(100 * (agora / antes - 1), 1), "desde": str(desde) if desde else None,
                             "impacto_mensal": round((agora - antes) * DIAS_MES, 2)})
    aumentos.sort(key=lambda x: -x["impacto_mensal"])

    # showback e cobertura de tags
    por_cc, por_app = defaultdict(float), defaultdict(float)
    com_tags = 0.0
    for n, c in custo_mes_rec.items():
        tags = meta[n]["tags"]
        por_cc[tags.get("centro_custo") or "(sem centro de custo)"] += c
        por_app[tags.get("app") or "(sem app)"] += c
        if tags.get("owner") and tags.get("centro_custo"):
            com_tags += c
    sem_tags = sorted(n for n in custo_mes_rec if not (meta[n]["tags"].get("owner") and meta[n]["tags"].get("centro_custo")))

    # oportunidades: inventário do Resource Graph deste tenant
    oportunidades, avaliados = [], []
    for item in dados["inventario"]:
        if item.get("tenantId") != tid:
            continue
        tipo = TIPOS.get(item["type"].lower())
        if not tipo:
            continue
        nome, p = item["name"], item.get("properties") or {}
        c = custo_mes_rec.get(nome, 0.0)
        regra, fator, evidencia = None, 1.0, ""
        if tipo == "disco" and p.get("diskState") == "Unattached":
            regra, evidencia = "disco_orfao", "diskState = Unattached (nenhuma VM usa o disco)"
        elif tipo == "ip" and "ipConfiguration" in p and p["ipConfiguration"] is None:
            regra, evidencia = "ip_orfao", "sem ipConfiguration (não está associado a nada)"
        elif tipo == "snapshot" and p.get("timeCreated"):
            idade = (corte - datetime.fromisoformat(p["timeCreated"].replace("Z", "+00:00")).date()).days
            if idade > SNAPSHOT_VELHO_DIAS:
                regra, evidencia = "snapshot_antigo", f"criado há {idade} dias (limite: {SNAPSHOT_VELHO_DIAS})"
        elif tipo == "vm":
            cpu = ((item.get("metricas") or {}).get("Percentage CPU") or {}).get("valor")
            if cpu is not None and cpu < CPU_P95_LIMITE:
                regra, fator = "vm_superdimensionada", FATOR_RIGHTSIZING
                evidencia = (f"CPU P95 de 14 dias = {br(cpu, 0)}% (limite: {CPU_P95_LIMITE:.0f}%), "
                             f"tamanho atual {p.get('hardwareProfile', {}).get('vmSize', '?')}")
        avaliados.append(nome)
        if regra:
            oportunidades.append({"recurso": nome, "tipo": regra, "economia_mensal": round(c * fator, 2),
                                  "custo_mensal": c, "evidencia": evidencia, "acao": ACAO[regra],
                                  "dono": meta.get(nome, {}).get("tags", {}).get("owner") or "(sem dono)",
                                  "grupo": item.get("resourceGroup")})
    oportunidades.sort(key=lambda o: -o["economia_mensal"])
    nao = sorted(n for n in avaliados if n not in {o["recurso"] for o in oportunidades})

    # economia realizada: medida nos dados, antes × depois de cada ação implementada
    realizadas = []
    for a in dados["acoes"]:
        if a.get("tenant") != tid:
            continue
        impl = date.fromisoformat(a["implementada_em"])
        s = recursos.get(a["recurso"], {})
        antes = sum(s.get(impl - timedelta(days=i), 0.0) for i in range(1, 31)) / 30
        dias_depois = (corte - impl).days + 1
        depois = sum(v for d, v in s.items() if d >= impl) / dias_depois if dias_depois > 0 else 0.0
        realizadas.append({**a, "custo_diario_antes": round(antes, 4), "custo_diario_depois": round(depois, 4),
                           "economia_mensal": round((antes - depois) * DIAS_MES, 2), "dias_medidos_depois": dias_depois,
                           "comprovada": depois == 0})

    return {"id": tid, "nome": tenant["nome"], "corte": str(corte),
            "custo_ultimos_30_dias": round(total30, 2), "custo_mes_ate_corte": round(ate_hoje, 2),
            "previsao_mes": round(previsao, 2), "orcamento_mensal": orcamento,
            "pct_orcamento": round(100 * previsao / orcamento, 1) if orcamento else None, "aumentos": aumentos,
            "estoura_orcamento": bool(orcamento) and previsao > orcamento,
            "cobertura_tags_pct": round(100 * com_tags / total30, 1) if total30 else 0.0, "sem_tags": sem_tags,
            "showback_centro_custo": dict(sorted(((k, round(v, 2)) for k, v in por_cc.items()), key=lambda x: -x[1])),
            "showback_app": dict(sorted(((k, round(v, 2)) for k, v in por_app.items()), key=lambda x: -x[1])),
            "top_recursos": sorted(custo_mes_rec.items(), key=lambda x: -x[1])[:5],
            "oportunidades": oportunidades,
            "economia_potencial_mensal": round(sum(o["economia_mensal"] for o in oportunidades), 2),
            "nao_sao_oportunidades": nao, "realizadas": realizadas,
            "economia_realizada_mensal": round(sum(r["economia_mensal"] for r in realizadas), 2),
            "recursos": sorted(recursos)}


def analisar_todos(dados):
    return [analisar(dados, t) for t in dados["tenants"]]


# ------------------------------------------------------------------ saídas
def _mes(d):
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{MESES[d.month - 1]}/{d.year}"


def _corte_br(d):
    return date.fromisoformat(d).strftime("%d/%m/%Y")


def texto_consolidado(analises):
    L = [f"Visão FinOps por tenant (dados até {_corte_br(analises[0]['corte'])}; valores em R$)", "",
         "Tenant | Custo 30 dias | Previsão do mês | Orçamento | % do orçamento | Economia potencial/mês | "
         "Economia realizada/mês | Cobertura de tags", "---|---|---|---|---|---|---|---"]
    for a in analises:
        alerta = " (VAI ESTOURAR)" if a["estoura_orcamento"] else ""
        L.append(f"{a['nome']} | {rs(a['custo_ultimos_30_dias'])} | {rs(a['previsao_mes'])} | {rs(a['orcamento_mensal'])} | "
                 f"{br(a['pct_orcamento'], 1)}%{alerta} | {rs(a['economia_potencial_mensal'])} | "
                 f"{rs(a['economia_realizada_mensal'])} | {br(a['cobertura_tags_pct'], 1)}%")
    tot_pot = sum(a["economia_potencial_mensal"] for a in analises)
    tot_real = sum(a["economia_realizada_mensal"] for a in analises)
    L += ["", f"Total: economia potencial {rs(tot_pot)}/mês ({rs(tot_pot * 12)}/ano) · economia realizada {rs(tot_real)}/mês.",
          "Estouram o orçamento neste mês: " + (", ".join(a["nome"] for a in analises if a["estoura_orcamento"]) or "nenhum") + "."]
    return "\n".join(L)


def texto_tenant(a):
    L = [f"Tenant: {a['nome']} (dados até {_corte_br(a['corte'])})",
         f"Custo dos últimos 30 dias: {rs(a['custo_ultimos_30_dias'])}",
         f"Mês de {_mes(a['corte'])}: {rs(a['custo_mes_ate_corte'])} até agora, previsão {rs(a['previsao_mes'])} "
         f"para um orçamento de {rs(a['orcamento_mensal'])} ({br(a['pct_orcamento'], 1)}%)"
         + (" → VAI ESTOURAR O ORÇAMENTO" if a["estoura_orcamento"] else " → dentro do orçamento"),
         *[f"O que mais subiu: {x['recurso']} de {rs(x['media_diaria_antes'])}/dia para {rs(x['media_diaria_agora'])}/dia "
           f"(+{br(x['aumento_pct'], 0)}%{', desde ' + _corte_br(x['desde']) if x['desde'] else ''}), "
           f"cerca de {rs(x['impacto_mensal'])} a mais por mês" for x in a["aumentos"][:1]],
         f"Cobertura de tags (owner + centro_custo): {br(a['cobertura_tags_pct'], 1)}% do custo"
         + (f"; sem tags: {', '.join(a['sem_tags'])}" if a["sem_tags"] else ""),
         "", "Custo por centro de custo (30 dias):"]
    L += [f"  {k}: {rs(v)}" for k, v in a["showback_centro_custo"].items()]
    L += ["", "Maiores custos (30 dias):"] + [f"  {n}: {rs(v)}" for n, v in a["top_recursos"]]
    L += ["", f"Economia potencial: {rs(a['economia_potencial_mensal'])}/mês ({len(a['oportunidades'])} oportunidade(s))"]
    L += [f"  {o['recurso']}: {NOME_OPORTUNIDADE[o['tipo']]} → {rs(o['economia_mensal'])}/mês" for o in a["oportunidades"]]
    if not a["oportunidades"]:
        L.append("  nenhuma oportunidade encontrada pelas regras (discos, IPs, snapshots e VMs conferidos)")
    L += [f"Economia realizada: {rs(a['economia_realizada_mensal'])}/mês"]
    L += [f"  {r['recurso']}: {r['acao']} em {_corte_br(r['implementada_em'])} → {rs(r['economia_mensal'])}/mês "
          f"({'comprovada: custo zerou nos dados' if r['comprovada'] else 'parcial: ainda há custo depois'})"
          for r in a["realizadas"]]
    return "\n".join(L)


def texto_economia(a):
    L = [f"Oportunidades de economia de {a['nome']} (dados até {_corte_br(a['corte'])}):"]
    if not a["oportunidades"]:
        L.append("Nenhuma oportunidade encontrada pelas regras. Conferidos: " + (", ".join(a["nao_sao_oportunidades"]) or "nenhum"))
    for i, o in enumerate(a["oportunidades"], 1):
        L += [f"{i}. {o['recurso']} ({NOME_OPORTUNIDADE[o['tipo']]}) → economia de {rs(o['economia_mensal'])}/mês",
              f"   evidência: {o['evidencia']}; custo atual {rs(o['custo_mensal'])}/mês",
              f"   ação: {o['acao']}; dono: {o['dono']}; grupo: {o['grupo']}"]
    if a["nao_sao_oportunidades"] and a["oportunidades"]:
        L.append("Conferidos e sem desperdício: " + ", ".join(a["nao_sao_oportunidades"]))
    L.append(f"Total: {rs(a['economia_potencial_mensal'])}/mês ({rs(a['economia_potencial_mensal'] * 12)}/ano)")
    return "\n".join(L)


def relatorio_executivo(a):
    estouro = a["estoura_orcamento"]
    L = [f"# Relatório executivo FinOps: {a['nome']}", "",
         f"> {_mes(a['corte']).capitalize()}, dados até {_corte_br(a['corte'])}. Gerado em código (tools/finops_tenants.py), "
         "sem IA, a partir da exportação FOCUS e do inventário do Azure deste tenant. Dados fictícios de demonstração.", "",
         "## Em uma linha", ""]
    frase = (f"O mês deve fechar em **{rs(a['previsao_mes'])}**, "
             + (f"**{br(a['pct_orcamento'] - 100, 1)}% acima do orçamento** de {rs(a['orcamento_mensal'])}. "
                if estouro else f"dentro do orçamento de {rs(a['orcamento_mensal'])} ({br(a['pct_orcamento'], 1)}%). ")
             + (f"Há **{rs(a['economia_potencial_mensal'])} por mês** que podem ser economizados agora"
                f" ({rs(a['economia_potencial_mensal'] * 12)} por ano)."
                if a["oportunidades"] else "Nenhum desperdício encontrado pelas regras de economia."))
    L += [frase, "", "## Indicadores", "", "| Indicador | Valor |", "|---|---|",
          f"| Custo dos últimos 30 dias | {rs(a['custo_ultimos_30_dias'])} |",
          f"| Previsão do mês × orçamento | {rs(a['previsao_mes'])} × {rs(a['orcamento_mensal'])} ({br(a['pct_orcamento'], 1)}%) |",
          f"| Economia potencial | {rs(a['economia_potencial_mensal'])}/mês |",
          f"| Economia realizada (medida) | {rs(a['economia_realizada_mensal'])}/mês |",
          f"| Custo com dono e centro de custo | {br(a['cobertura_tags_pct'], 1)}% |", "", "## O que fazer agora", ""]
    if a["oportunidades"]:
        L += ["| # | Recurso | Problema | Economia/mês | Ação | Dono |", "|---|---|---|---|---|---|"]
        L += [f"| {i} | `{o['recurso']}` | {NOME_OPORTUNIDADE[o['tipo']]}: {o['evidencia']} | {rs(o['economia_mensal'])} | "
              f"{o['acao']} | {o['dono']} |" for i, o in enumerate(a["oportunidades"], 1)]
    else:
        L.append("- Nenhuma ação de economia pendente pelas regras atuais.")
    if estouro:
        L += ["", f"- **Orçamento:** a previsão passa o orçamento em {rs(a['previsao_mes'] - a['orcamento_mensal'])}."]
        if a["aumentos"]:
            x = a["aumentos"][0]
            L[-1] += (f" A causa é `{x['recurso']}`: o custo diário subiu de {rs(x['media_diaria_antes'])} para "
                      f"{rs(x['media_diaria_agora'])} (+{br(x['aumento_pct'], 0)}%)"
                      + (f" desde {_corte_br(x['desde'])}" if x["desde"] else "")
                      + f", cerca de {rs(x['impacto_mensal'])} a mais por mês. Confirmar com o dono se a mudança foi "
                      "planejada: se foi, ajustar o orçamento; se não, voltar a configuração.")
    if a["sem_tags"]:
        L += ["", f"- **Prestação de contas:** {len(a['sem_tags'])} recurso(s) sem dono ou centro de custo "
              f"({', '.join(f'`{n}`' for n in a['sem_tags'])}). Exigir as tags com Azure Policy."]
    L += ["", "## Quem gasta (últimos 30 dias)", "", "| Centro de custo | Custo | % |", "|---|---|---|"]
    tot = a["custo_ultimos_30_dias"] or 1
    L += [f"| {k} | {rs(v)} | {br(100 * v / tot, 1)}% |" for k, v in a["showback_centro_custo"].items()]
    if a["realizadas"]:
        L += ["", "## Economia já realizada", "", "| Ação | Implementada | Antes (por dia) | Depois (por dia) | Economia/mês |",
              "|---|---|---|---|---|"]
        L += [f"| {r['acao']} (`{r['recurso']}`) | {_corte_br(r['implementada_em'])} | {rs(r['custo_diario_antes'])} | "
              f"{rs(r['custo_diario_depois'])} | {rs(r['economia_mensal'])} |" for r in a["realizadas"]]
    L += ["", "## Como os números foram calculados", "",
          "- Custo: exportação FOCUS do Cost Management (EffectiveCost), só deste tenant.",
          f"- Previsão: custo do mês até o corte + média diária dos últimos {DIAS_TENDENCIA} dias × dias restantes.",
          "- Oportunidades: inventário do Azure Resource Graph (disco Unattached, IP sem associação, snapshot com mais de "
          f"{SNAPSHOT_VELHO_DIAS} dias) e CPU P95 de 14 dias do Azure Monitor (abaixo de {CPU_P95_LIMITE:.0f}%: estimativa de "
          f"{FATOR_RIGHTSIZING:.0%} de economia com um tamanho abaixo).",
          "- Economia realizada: custo diário medido antes e depois de cada ação implementada."]
    return "\n".join(L) + "\n"


def slug(nome):
    return _sem_acento(nome).split()[0]


def consolidado_md(analises):
    L = ["# Relatório executivo FinOps: visão consolidada", "",
         f"> Dados até {_corte_br(analises[0]['corte'])}. Uso interno do time de FinOps: cada cliente recebe só o próprio "
         "relatório. Gerado em código, dados fictícios.", "",
         "| Tenant | Custo 30 dias | Previsão × orçamento | Economia potencial/mês | Economia realizada/mês | Tags |",
         "|---|---|---|---|---|---|"]
    for a in analises:
        L.append(f"| [{a['nome']}]({slug(a['nome'])}.md) | {rs(a['custo_ultimos_30_dias'])} | {br(a['pct_orcamento'], 1)}%"
                 f"{' ⚠️' if a['estoura_orcamento'] else ''} | {rs(a['economia_potencial_mensal'])} | "
                 f"{rs(a['economia_realizada_mensal'])} | {br(a['cobertura_tags_pct'], 1)}% |")
    pot = sum(a["economia_potencial_mensal"] for a in analises)
    L += ["", f"**Economia potencial somada:** {rs(pot)}/mês ({rs(pot * 12)}/ano). "
          f"**Realizada:** {rs(sum(a['economia_realizada_mensal'] for a in analises))}/mês."]
    return "\n".join(L) + "\n"


def gerar_executivos(dados, tenant=None):
    SAIDA.mkdir(parents=True, exist_ok=True)
    alvos = [tenant] if tenant else dados["tenants"]
    arquivos = []
    for t in alvos:
        a = analisar(dados, t)
        arq = SAIDA / f"{slug(t['nome'])}.md"
        arq.write_text(relatorio_executivo(a), encoding="utf-8")
        arquivos.append(arq)
    if not tenant:
        arq = SAIDA / "consolidado.md"
        arq.write_text(consolidado_md(analisar_todos(dados)), encoding="utf-8")
        arquivos.append(arq)
    return arquivos


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv:
        print(__doc__)
        return 1
    cmd, resto = argv[0], [x for x in argv[1:] if not x.startswith("--")]
    dados = carregar()
    nome = " ".join(resto) or os.environ.get("tenant", "")
    if cmd == "tenants":
        analises = analisar_todos(dados)
        print(json.dumps(analises, ensure_ascii=False, default=str) if "--json" in argv else texto_consolidado(analises))
        print("RESULTADO: OK")
        return 0
    if cmd in ("tenant", "economia") or (cmd == "executivo" and nome):
        t = achar_tenant(dados, nome)
        if not t:
            print(f"Tenant '{nome}' não encontrado. Tenants: {', '.join(x['nome'] for x in dados['tenants'])}.")
            print("RESULTADO: TENANT NÃO ENCONTRADO")
            return 0
        if cmd == "executivo":
            arqs = gerar_executivos(dados, t)
        else:
            a = analisar(dados, t)
            print(json.dumps(a, ensure_ascii=False, default=str) if "--json" in argv else
                  (texto_tenant(a) if cmd == "tenant" else texto_economia(a)))
            print("RESULTADO: OK")
            return 0
    elif cmd == "executivo":
        arqs = gerar_executivos(dados)
    else:
        print(__doc__)
        return 1
    for a in arqs:
        print(f"- {a.relative_to(ROOT).as_posix() if a.is_relative_to(ROOT) else a}")
    print("RESULTADO: RELATÓRIOS EXECUTIVOS GERADOS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
