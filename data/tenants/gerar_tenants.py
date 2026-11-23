"""Gera dados SINTÉTICOS de uma empresa com 3 tenants, um por ambiente (produção, desenvolvimento e integração),
para a visão FinOps multi-tenant. É o caso de uma área de Automação e Integração que separa os ambientes em tenants.

Saídas nesta pasta (tudo fictício, com nomes de exemplo da própria Microsoft):
  tenants.json        os tenants: id, nome, ambiente, assinaturas e orçamento mensal
  focus_tenants.csv   custo diário no formato FOCUS (mesmas colunas de data/focus_costs.csv) + x_TenantId/x_TenantNome
  inventario.json     estado dos recursos como o Azure Resource Graph devolve (disco Attached/Unattached, IP sem
                      ipConfiguration, data do snapshot, tamanho da VM) + CPU P95 de 14 dias (Azure Monitor)
  acoes.json          ações de economia já implementadas (para medir a economia REALIZADA nos dados)
  gabarito.json       o que a análise tem que achar: custos, previsão × orçamento, cobertura de tags, cada
                      oportunidade com o valor exato, o que NÃO é oportunidade e a economia realizada

Os valores esperados são calculados aqui, a partir do plano de cada recurso, por um caminho separado do código
da análise (tools/finops_tenants.py). Assim o teste compara dois cálculos independentes.

Uso:  python data/tenants/gerar_tenants.py
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 7
INICIO = date(2026, 8, 1)
CORTE = date(2026, 11, 20)  # último dia com dados ("hoje" da análise)
PASTA = Path(__file__).resolve().parent
REGIAO = ("brazilsouth", "Brazil South")
USD = 0.18

# regras da análise (as mesmas documentadas em tools/finops_tenants.py)
DIAS_MES = 30
SNAPSHOT_VELHO_DIAS = 90
CPU_P95_LIMITE = 20.0
FATOR_RIGHTSIZING = 0.5
DIAS_TENDENCIA = 7
JANELA_24X7 = 28            # dias usados para ver se a VM fica ligada no fim de semana
RAZAO_24X7 = 0.9            # custo no fim de semana >= 90% do dia útil: VM ligada 24x7
HORAS_UTEIS_SEMANA = 60     # ligada 12 h por dia útil (7h às 19h), desligada à noite e no fim de semana
LIMITE_APP_NAO_PROD = 50.0  # app que custa em dev/integração 50% ou mais do que custa em produção

TENANTS = [
    {"id": "11111111-1111-1111-1111-111111111111", "nome": "Contoso Produção", "slug": "producao", "ambiente": "producao", "apelidos": ["prod", "prd"],
     "orcamento_mensal": 9000.0, "assinaturas": {"prod": "sub-integracao-prd"}},
    {"id": "22222222-2222-2222-2222-222222222222", "nome": "Contoso Desenvolvimento", "slug": "desenvolvimento",
     "ambiente": "desenvolvimento", "apelidos": ["dev"], "orcamento_mensal": 3200.0, "assinaturas": {"dev": "sub-integracao-dev"}},
    {"id": "33333333-3333-3333-3333-333333333333", "nome": "Contoso Integração", "slug": "integracao", "ambiente": "integracao", "apelidos": ["hml", "homologacao", "int"],
     "orcamento_mensal": 3600.0, "assinaturas": {"hml": "sub-integracao-hml"}},
]

VM, DISCO, IP, SNAP = ("microsoft.compute/virtualmachines", "microsoft.compute/disks", "microsoft.network/publicipaddresses",
                       "microsoft.compute/snapshots")
SERVICOS = {
    VM: ("Virtual Machines", "Compute", "Virtual Machines", "Hours"),
    DISCO: ("Storage", "Storage", "Storage", "GB/Month"),
    IP: ("Virtual Network", "Networking", "Virtual Network", "IP Hours"),
    SNAP: ("Storage", "Storage", "Storage", "GB/Month"),
    "microsoft.sql/servers/databases": ("SQL Database", "Databases", "SQL Database", "vCore Hours"),
    "microsoft.storage/storageaccounts": ("Storage", "Storage", "Storage", "GB/Month"),
    "microsoft.containerservice/managedclusters": ("Azure Kubernetes Service", "Compute", "Virtual Machines", "Hours"),
    "microsoft.web/sites": ("Functions", "Compute", "Functions", "Executions"),
    "microsoft.logic/workflows": ("Logic Apps", "Integration", "Logic Apps", "Actions"),
    "microsoft.apimanagement/service": ("API Management", "Integration", "API Management", "Units"),
    "microsoft.insights/components": ("Azure Monitor", "Management and Governance", "Log Analytics", "GB"),
}


def T(owner=None, cc=None, app=None, env="prod"):
    t = {"env": env}
    if owner:
        t["owner"] = owner
    if cc:
        t["centro_custo"] = cc
    if app:
        t["app"] = app
    return t


LA, FUNC, SQL, APIM, STG, APPI = ("microsoft.logic/workflows", "microsoft.web/sites", "microsoft.sql/servers/databases",
                                  "microsoft.apimanagement/service", "microsoft.storage/storageaccounts",
                                  "microsoft.insights/components")

# tenant, assinatura, nome, rg, tipo, custo diário, tags, inventário, plano especial
# plano especial: "ate" (excluído depois do dia), "degrau" (muda de valor numa data), "inicio" (criado na data),
#                 "auto_shutdown" (liga só 12 h nos dias úteis: custo pela metade e zero no fim de semana)
RECURSOS = [
    # ---------------- Produção
    ("producao", "prod", "lgc-pedidos-prd", "rg-pedidos-prd", LA, 6.5, T("integracao", "CC-410", "pedidos"), {}, None),
    ("producao", "prod", "func-pedidos-prd", "rg-pedidos-prd", FUNC, 4.2, T("integracao", "CC-410", "pedidos"), {}, None),
    ("producao", "prod", "sqldb-pedidos-prd", "rg-pedidos-prd", SQL, 48.0, T("integracao", "CC-410", "pedidos"), {}, None),
    ("producao", "prod", "apim-integracao-prd", "rg-apim-prd", APIM, 92.0, T("integracao", "CC-420", "integracao-erp"), {}, None),
    ("producao", "prod", "vm-erp-conector-prd", "rg-erp-prd", VM, 41.0, T("integracao", "CC-420", "integracao-erp"), {"vmSize": "Standard_D8s_v5", "cpu_p95": 11.0}, None),
    ("producao", "prod", "disk-dados-01", "rg-erp-prd", DISCO, 3.8, T("integracao", "CC-420", "integracao-erp"), {"diskState": "Attached", "managedBy": "vm-erp-conector-prd"}, None),
    ("producao", "prod", "stgintegracaoprd", "rg-erp-prd", STG, 9.0, T("integracao", "CC-420", "integracao-erp"), {}, None),
    ("producao", "prod", "appi-integracao-prd", "rg-monitoramento-prd", APPI, 7.5, T("integracao"), {}, None),
    # ---------------- Desenvolvimento (VM de carga criada em 06/11 e esquecida ligada → estoura o orçamento)
    ("desenvolvimento", "dev", "lgc-pedidos-dev", "rg-pedidos-dev", LA, 1.1, T("integracao", "CC-410", "pedidos", "dev"), {}, None),
    ("desenvolvimento", "dev", "sqldb-pedidos-dev", "rg-pedidos-dev", SQL, 31.0, T("integracao", "CC-410", "pedidos", "dev"), {}, None),
    ("desenvolvimento", "dev", "vm-build-dev", "rg-pipeline-dev", VM, 19.2, T("integracao", "CC-430", "pipeline", "dev"), {"vmSize": "Standard_D4s_v5", "cpu_p95": 30.0}, None),
    ("desenvolvimento", "dev", "vm-teste-dev", "rg-pedidos-dev", VM, 9.6, T("integracao", "CC-410", "pedidos", "dev"), {"vmSize": "Standard_B4ms", "cpu_p95": 45.0}, {"auto_shutdown": True}),
    ("desenvolvimento", "dev", "vm-carga-dev", "rg-pedidos-dev", VM, 76.8, T("integracao", "CC-410", "pedidos", "dev"), {"vmSize": "Standard_D16s_v5", "cpu_p95": 8.0}, {"inicio": "2026-11-06"}),
    ("desenvolvimento", "dev", "snap-build-dev-2026-03", "rg-pipeline-dev", SNAP, 2.4, T("integracao", "CC-430", "pipeline", "dev"), {"timeCreated": "2026-03-15T03:00:00Z"}, None),
    ("desenvolvimento", "dev", "pip-teste-dev", "rg-pedidos-dev", IP, 0.95, {}, {"ipConfiguration": None}, None),
    ("desenvolvimento", "dev", "disk-dados-01", "rg-pedidos-dev", DISCO, 3.8, T("integracao", "CC-410", "pedidos", "dev"), {"diskState": "Unattached", "managedBy": None}, None),
    # ---------------- Integração (disco órfão excluído em 14/10 → economia realizada)
    ("integracao", "hml", "apim-integracao-hml", "rg-apim-hml", APIM, 40.0, T("integracao", "CC-420", "integracao-erp", "hml"), {}, None),
    ("integracao", "hml", "vm-hml-01", "rg-erp-hml", VM, 19.2, T("integracao", "CC-420", "integracao-erp", "hml"), {"vmSize": "Standard_D4s_v5", "cpu_p95": 22.0}, None),
    ("integracao", "hml", "sqldb-pedidos-hml", "rg-pedidos-hml", SQL, 18.0, T("integracao", "CC-410", "pedidos", "hml"), {}, None),
    ("integracao", "hml", "disk-hml-antigo", "rg-erp-hml", DISCO, 5.1, T("integracao", "CC-420", "integracao-erp", "hml"), {"excluido": "2026-10-14"}, {"ate": "2026-10-13"}),
    ("integracao", "hml", "stghml", "rg-erp-hml", STG, 3.5, {}, {}, None),
]

ACOES = [{"id": "E-001", "tenant": "33333333-3333-3333-3333-333333333333", "recurso": "disk-hml-antigo",
          "acao": "Excluir disco gerenciado sem VM (Unattached)", "aprovada_em": "2026-10-10", "implementada_em": "2026-10-14",
          "responsavel": "integracao"}]


def dias():
    d = INICIO
    while d <= CORTE:
        yield d
        d += timedelta(days=1)


def custo_do_dia(plano, base, d, rng):
    especial = plano[8] or {}
    if "ate" in especial and d > date.fromisoformat(especial["ate"]):
        return None  # recurso excluído: não gera mais custo
    if "inicio" in especial and d < date.fromisoformat(especial["inicio"]):
        return None  # recurso ainda não existia
    valor = base
    if especial.get("auto_shutdown"):
        if d.weekday() >= 5:
            return None  # desligada no fim de semana: sem linha de custo de computação
        valor = base * 12 / 24
    if "degrau" in especial and d >= date.fromisoformat(especial["degrau"][0]):
        valor = especial["degrau"][1]
    return round(valor * rng.uniform(0.94, 1.06), 4)


def main():
    rng = random.Random(SEED)
    tenants = {t["slug"]: t for t in TENANTS}
    linhas, serie = [], {}
    for d in dias():
        for plano in RECURSOS:
            slug, sub, nome, rg, tipo, base, tags = plano[:7]
            v = custo_do_dia(plano, base, d, rng)
            if v is None:
                continue
            t = tenants[slug]
            sub_nome = t["assinaturas"][sub]
            sub_id = f"/subscriptions/{t['id'][:8]}-{sub_nome[-4:]}-0000-0000-000000000000"
            servico, categoria, medidor, unidade = SERVICOS[tipo]
            serie.setdefault((slug, nome), {})[d] = v
            inicio_mes = d.replace(day=1)
            fim_mes = (inicio_mes + timedelta(days=32)).replace(day=1)
            linhas.append({
                "BilledCost": v, "EffectiveCost": v, "ListCost": round(v * 1.05, 4), "BillingCurrency": "BRL",
                "BillingPeriodStart": f"{inicio_mes}T00:00:00Z", "BillingPeriodEnd": f"{fim_mes}T00:00:00Z",
                "ChargeCategory": "Usage", "ChargeDescription": f"{servico} - {medidor}",
                "ChargePeriodStart": f"{d}T00:00:00Z", "ChargePeriodEnd": f"{d + timedelta(days=1)}T00:00:00Z",
                "ConsumedQuantity": round(v / 0.5, 2), "ConsumedUnit": unidade, "PricingCategory": "Standard",
                "ProviderName": "Microsoft", "PublisherName": "Microsoft", "RegionId": REGIAO[0], "RegionName": REGIAO[1],
                "ResourceId": f"{sub_id}/resourcegroups/{rg}/providers/{tipo}/{nome}", "ResourceName": nome,
                "ResourceType": servico, "ServiceCategory": categoria, "ServiceName": servico,
                "SubAccountId": sub_id, "SubAccountName": sub_nome, "Tags": json.dumps(tags, ensure_ascii=False),
                "x_BilledCostInUsd": round(v * USD, 4), "x_ResourceGroupName": rg, "x_ResourceType": tipo,
                "x_SkuMeterCategory": medidor, "x_TenantId": t["id"], "x_TenantNome": t["nome"],
            })
    with (PASTA / "focus_tenants.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)

    # inventário no formato do Azure Resource Graph (só o que a análise usa) + CPU P95 do Azure Monitor
    inventario = []
    for plano in RECURSOS:
        slug, sub, nome, rg, tipo, _, tags, props, _ = plano
        if props.get("excluido"):
            continue  # recurso excluído não aparece mais no Resource Graph
        t = tenants[slug]
        sub_nome = t["assinaturas"][sub]
        sub_id = f"/subscriptions/{t['id'][:8]}-{sub_nome[-4:]}-0000-0000-000000000000"
        p = {k: v for k, v in props.items() if k not in ("cpu_p95", "desde")}
        if tipo == VM:
            p = {"hardwareProfile": {"vmSize": props["vmSize"]}}
        item = {"id": f"{sub_id}/resourcegroups/{rg}/providers/{tipo}/{nome}", "name": nome, "type": tipo,
                "tenantId": t["id"], "subscriptionId": sub_id.split("/")[-1], "resourceGroup": rg, "tags": tags,
                "properties": p}
        if "cpu_p95" in props:
            item["metricas"] = {"Percentage CPU": {"agregacao": "P95", "janela_dias": 14, "valor": props["cpu_p95"]}}
        inventario.append(item)
    (PASTA / "inventario.json").write_text(json.dumps(inventario, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (PASTA / "tenants.json").write_text(json.dumps(
        [{k: v for k, v in t.items() if k != "slug"} for t in TENANTS], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (PASTA / "acoes.json").write_text(json.dumps(ACOES, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ------------------------------------------------------------ gabarito (pelo plano, não pela análise)
    ultimos30 = [CORTE - timedelta(days=i) for i in range(DIAS_MES)]

    def custo30(slug, nome):
        s = serie.get((slug, nome), {})
        return round(sum(s.get(d, 0.0) for d in ultimos30), 2)

    gabarito = {"corte": str(CORTE), "regras": {
        "custo_mes_recurso": f"soma dos últimos {DIAS_MES} dias até o corte",
        "disco_orfao": "disco com diskState Unattached: economia = 100% do custo do mês",
        "ip_orfao": "IP público sem ipConfiguration: economia = 100% do custo do mês",
        "snapshot_antigo": f"snapshot com mais de {SNAPSHOT_VELHO_DIAS} dias: economia = 100% do custo do mês",
        "vm_superdimensionada": f"VM com CPU P95 (14 dias) abaixo de {CPU_P95_LIMITE:.0f}%: economia = "
                                f"{FATOR_RIGHTSIZING:.0%} do custo do mês (um tamanho abaixo)",
        "vm_ligada_24x7": f"fora de produção, VM que custa no fim de semana >= {RAZAO_24X7:.0%} do dia útil "
                          f"(últimos {JANELA_24X7} dias): economia = custo do mês × (1 − {HORAS_UTEIS_SEMANA}/168), "
                          "ligando só em horário comercial; tem prioridade sobre a regra de CPU",
        "custo_nao_produtivo_pct": "custo de desenvolvimento + integração ÷ custo de produção (30 dias)",
        "app_nao_prod_alto": f"app (tag app) que custa fora de produção {LIMITE_APP_NAO_PROD:.0f}% ou mais do que em produção",
        "previsao_mes": f"custo do mês até o corte + média dos últimos {DIAS_TENDENCIA} dias × dias restantes",
        "economia_realizada": "ação implementada e custo zerado depois dela: média diária dos 30 dias antes × 30"},
        "tenants": {}}
    for t in TENANTS:
        slug = t["slug"]
        recursos = [p for p in RECURSOS if p[0] == slug]
        ops, nao = [], []
        for p in recursos:
            _, _, nome, _, tipo, _, tags, props, _ = p
            if props.get("excluido"):
                continue
            c = custo30(slug, nome)
            regra = None
            if tipo == DISCO and props.get("diskState") == "Unattached":
                regra, fator = "disco_orfao", 1.0
            elif tipo == IP and props.get("ipConfiguration", "x") is None:
                regra, fator = "ip_orfao", 1.0
            elif tipo == SNAP and (CORTE - date.fromisoformat(props["timeCreated"][:10])).days > SNAPSHOT_VELHO_DIAS:
                regra, fator = "snapshot_antigo", 1.0
            elif tipo == VM and t["ambiente"] != "producao" and not (p[8] or {}).get("auto_shutdown"):
                regra, fator = "vm_ligada_24x7", 1 - HORAS_UTEIS_SEMANA / 168
            elif tipo == VM and props["cpu_p95"] < CPU_P95_LIMITE:
                regra, fator = "vm_superdimensionada", FATOR_RIGHTSIZING
            if regra:
                ops.append({"recurso": nome, "tipo": regra, "economia_mensal": round(c * fator, 2)})
            elif tipo in (DISCO, IP, SNAP, VM):
                nao.append(nome)
        mes = [d for d in dias() if d.month == CORTE.month and d.year == CORTE.year]
        ate_hoje = sum(serie[(slug, p[2])].get(d, 0.0) for p in recursos for d in mes)
        ult7 = [CORTE - timedelta(days=i) for i in range(DIAS_TENDENCIA)]
        media7 = sum(serie[(slug, p[2])].get(d, 0.0) for p in recursos for d in ult7) / DIAS_TENDENCIA
        fim = (CORTE.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        previsao = ate_hoje + media7 * (fim - CORTE).days
        total30 = sum(custo30(slug, p[2]) for p in recursos)
        com_tags = sum(custo30(slug, p[2]) for p in recursos if p[6].get("owner") and p[6].get("centro_custo"))
        realizada = 0.0
        for a in ACOES:
            if a["tenant"] != t["id"]:
                continue
            impl = date.fromisoformat(a["implementada_em"])
            antes = [impl - timedelta(days=i) for i in range(1, 31)]
            s = serie[(slug, a["recurso"])]
            realizada += sum(s.get(d, 0.0) for d in antes) / 30 * DIAS_MES
        gabarito["tenants"][t["id"]] = {
            "nome": t["nome"], "ambiente": t["ambiente"], "custo_ultimos_30_dias": round(total30, 2), "custo_mes_ate_corte": round(ate_hoje, 2),
            "previsao_mes": round(previsao, 2), "orcamento_mensal": t["orcamento_mensal"],
            "estoura_orcamento": previsao > t["orcamento_mensal"],
            "cobertura_tags_pct": round(100 * com_tags / total30, 1),
            "oportunidades": sorted(ops, key=lambda o: -o["economia_mensal"]),
            "economia_potencial_mensal": round(sum(o["economia_mensal"] for o in ops), 2),
            "nao_sao_oportunidades": sorted(nao), "economia_realizada_mensal": round(realizada, 2),
            "causa_aumento": [{"recurso": p[2], "desde": (p[8].get("degrau") or [p[8].get("inicio")])[0],
                               "recurso_novo": "inicio" in p[8]}
                              for p in recursos if p[8] and ("degrau" in p[8] or "inicio" in p[8])],
            "recursos": sorted(p[2] for p in recursos)}
    # consolidado da empresa: quanto custa o que não é produção e, por app, quanto dev/integração custam perto de produção
    por_amb = {}
    apps = {}
    for t in TENANTS:
        for p in RECURSOS:
            if p[0] != t["slug"]:
                continue
            c = custo30(t["slug"], p[2])
            por_amb[t["ambiente"]] = por_amb.get(t["ambiente"], 0.0) + c
            app = p[6].get("app")
            if app:
                lado = "producao" if t["ambiente"] == "producao" else "nao_producao"
                apps.setdefault(app, {"producao": 0.0, "nao_producao": 0.0})[lado] += c
    prod = por_amb.get("producao", 0.0)
    gabarito["empresa"] = {
        "custo_por_ambiente": {k: round(v, 2) for k, v in por_amb.items()},
        "custo_nao_produtivo_pct": round(100 * (sum(por_amb.values()) - prod) / prod, 1),
        "apps": {a: {"producao": round(v["producao"], 2), "nao_producao": round(v["nao_producao"], 2),
                     "pct": round(100 * v["nao_producao"] / v["producao"], 1) if v["producao"] else None}
                 for a, v in sorted(apps.items())},
        "apps_nao_prod_alto": sorted(a for a, v in apps.items()
                                     if v["producao"] and 100 * v["nao_producao"] / v["producao"] >= LIMITE_APP_NAO_PROD)}
    (PASTA / "gabarito.json").write_text(json.dumps(gabarito, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(linhas)} linhas de custo, {len(inventario)} recursos no inventário, {len(TENANTS)} tenants")
    print(f"  não produtivo ÷ produção: {gabarito['empresa']['custo_nao_produtivo_pct']}% · apps altos fora de produção: "
          f"{gabarito['empresa']['apps_nao_prod_alto']}")
    for g in gabarito["tenants"].values():
        print(f"  {g['nome']}: 30 dias R$ {g['custo_ultimos_30_dias']:.2f} · previsão R$ {g['previsao_mes']:.2f} / "
              f"orçamento R$ {g['orcamento_mensal']:.2f} · economia potencial R$ {g['economia_potencial_mensal']:.2f}/mês · "
              f"realizada R$ {g['economia_realizada_mensal']:.2f}/mês · tags {g['cobertura_tags_pct']}%")


if __name__ == "__main__":
    main()
