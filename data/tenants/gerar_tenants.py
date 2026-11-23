"""Gera dados SINTÉTICOS de 3 tenants (clientes fictícios) para a visão FinOps multi-tenant.

Saídas nesta pasta (tudo fictício, com nomes de exemplo da própria Microsoft):
  tenants.json        os tenants: id, nome, assinaturas e orçamento mensal
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

TENANTS = [
    {"id": "11111111-1111-1111-1111-111111111111", "nome": "Contoso Varejo", "slug": "contoso",
     "orcamento_mensal": 9500.0,
     "assinaturas": {"prod": "sub-contoso-prod", "dev": "sub-contoso-dev"}},
    {"id": "22222222-2222-2222-2222-222222222222", "nome": "Fabrikam Saúde", "slug": "fabrikam",
     "orcamento_mensal": 6000.0,
     "assinaturas": {"prod": "sub-fabrikam-prod"}},
    {"id": "33333333-3333-3333-3333-333333333333", "nome": "Northwind Logística", "slug": "northwind",
     "orcamento_mensal": 3200.0,
     "assinaturas": {"prod": "sub-northwind-prod"}},
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


# tenant, assinatura, nome, rg, tipo, custo diário, tags, inventário, plano especial
RECURSOS = [
    # ---------------- Contoso Varejo
    ("contoso", "prod", "vm-pdv-api-01", "rg-pdv", VM, 38.4, T("loja", "CC-100", "pdv"), {"vmSize": "Standard_D8s_v5", "cpu_p95": 62.0}, None),
    ("contoso", "prod", "vm-relatorios-02", "rg-bi", VM, 76.8, T("bi", "CC-200", "relatorios"), {"vmSize": "Standard_D16s_v5", "cpu_p95": 9.0}, None),
    ("contoso", "prod", "sqldb-vendas", "rg-pdv", "microsoft.sql/servers/databases", 54.0, T("loja", "CC-100", "pdv"), {}, None),
    ("contoso", "prod", "aks-loja", "rg-loja-online", "microsoft.containerservice/managedclusters", 95.0, T("ecommerce", "CC-300", "loja-online"), {}, None),
    ("contoso", "prod", "stgcontosodados", "rg-bi", "microsoft.storage/storageaccounts", 12.5, T("bi", "CC-200", "relatorios"), {}, None),
    ("contoso", "prod", "disk-backup-01", "rg-pdv", DISCO, 4.9, T("loja", "CC-100", "pdv"), {"diskState": "Unattached", "managedBy": None, "desde": "2026-09-03"}, None),
    ("contoso", "prod", "pip-legado-01", "rg-legado", IP, 0.95, {}, {"ipConfiguration": None}, None),
    ("contoso", "prod", "snap-vm-pdv-2025-12", "rg-pdv", SNAP, 2.6, T("loja", "CC-100", "pdv"), {"timeCreated": "2025-12-10T03:00:00Z"}, None),
    ("contoso", "dev", "vm-dev-teste", "rg-dev", VM, 6.1, T("loja", "CC-100", "pdv", env="dev"), {"vmSize": "Standard_B4ms", "cpu_p95": 35.0}, None),
    # ---------------- Fabrikam Saúde (SQL escalado em 05/11 → estoura o orçamento de novembro)
    ("fabrikam", "prod", "vm-prontuario-01", "rg-prontuario", VM, 44.0, T("clinico", "CC-10", "prontuario"), {"vmSize": "Standard_D8s_v5", "cpu_p95": 71.0}, None),
    ("fabrikam", "prod", "sqldb-prontuario", "rg-prontuario", "microsoft.sql/servers/databases", 60.0, T("clinico", "CC-10", "prontuario"), {}, {"degrau": ("2026-11-05", 150.0)}),
    ("fabrikam", "prod", "disk-backup-01", "rg-prontuario", DISCO, 4.9, T("clinico", "CC-10", "prontuario"),
     {"diskState": "Attached", "managedBy": "vm-prontuario-01"}, None),
    ("fabrikam", "prod", "stgfabrikamimagens", "rg-imagens", "microsoft.storage/storageaccounts", 18.0, T("imagens", "CC-20", "pacs"), {}, None),
    ("fabrikam", "prod", "appi-fabrikam", "rg-monitoramento", "microsoft.insights/components", 9.0, T("ti"), {}, None),
    ("fabrikam", "prod", "snap-prontuario-2026-10", "rg-prontuario", SNAP, 1.8, T("clinico", "CC-10", "prontuario"), {"timeCreated": "2026-10-20T03:00:00Z"}, None),
    # ---------------- Northwind Logística (disco órfão excluído em 10/10 → economia realizada)
    ("northwind", "prod", "vm-rotas-01", "rg-rotas", VM, 30.0, T("operacoes", "CC-7", "rotas"), {"vmSize": "Standard_D8s_v5", "cpu_p95": 15.0}, None),
    ("northwind", "prod", "func-rastreio", "rg-rotas", "microsoft.web/sites", 7.5, T("operacoes", "CC-7", "rastreio"), {}, None),
    ("northwind", "prod", "sqldb-entregas", "rg-rotas", "microsoft.sql/servers/databases", 33.0, T("operacoes", "CC-7", "rotas"), {}, None),
    ("northwind", "prod", "disk-antigo-02", "rg-rotas", DISCO, 6.2, T("operacoes", "CC-7", "rotas"), {"excluido": "2026-10-10"}, {"ate": "2026-10-09"}),
    ("northwind", "prod", "pip-sem-uso-03", "rg-rotas", IP, 0.95, T("operacoes", "CC-7", "rotas"), {"ipConfiguration": None}, None),
    ("northwind", "prod", "stgnorthwindlogs", "rg-logs", "microsoft.storage/storageaccounts", 6.0, {}, {}, None),
]

ACOES = [{"id": "E-001", "tenant": "33333333-3333-3333-3333-333333333333", "recurso": "disk-antigo-02",
          "acao": "Excluir disco gerenciado sem VM (Unattached)", "aprovada_em": "2026-10-08", "implementada_em": "2026-10-10",
          "responsavel": "operacoes"}]


def dias():
    d = INICIO
    while d <= CORTE:
        yield d
        d += timedelta(days=1)


def custo_do_dia(plano, base, d, rng):
    especial = plano[8]
    if especial and "ate" in especial and d > date.fromisoformat(especial["ate"]):
        return None  # recurso excluído: não gera mais custo
    valor = base
    if especial and "degrau" in especial and d >= date.fromisoformat(especial["degrau"][0]):
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
            "nome": t["nome"], "custo_ultimos_30_dias": round(total30, 2), "custo_mes_ate_corte": round(ate_hoje, 2),
            "previsao_mes": round(previsao, 2), "orcamento_mensal": t["orcamento_mensal"],
            "estoura_orcamento": previsao > t["orcamento_mensal"],
            "cobertura_tags_pct": round(100 * com_tags / total30, 1),
            "oportunidades": sorted(ops, key=lambda o: -o["economia_mensal"]),
            "economia_potencial_mensal": round(sum(o["economia_mensal"] for o in ops), 2),
            "nao_sao_oportunidades": sorted(nao), "economia_realizada_mensal": round(realizada, 2),
            "causa_aumento": [{"recurso": p[2], "desde": p[8]["degrau"][0]} for p in recursos if p[8] and "degrau" in p[8]],
            "recursos": sorted(p[2] for p in recursos)}
    (PASTA / "gabarito.json").write_text(json.dumps(gabarito, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(linhas)} linhas de custo, {len(inventario)} recursos no inventário, {len(TENANTS)} tenants")
    for g in gabarito["tenants"].values():
        print(f"  {g['nome']}: 30 dias R$ {g['custo_ultimos_30_dias']:.2f} · previsão R$ {g['previsao_mes']:.2f} / "
              f"orçamento R$ {g['orcamento_mensal']:.2f} · economia potencial R$ {g['economia_potencial_mensal']:.2f}/mês · "
              f"realizada R$ {g['economia_realizada_mensal']:.2f}/mês · tags {g['cobertura_tags_pct']}%")


if __name__ == "__main__":
    main()
