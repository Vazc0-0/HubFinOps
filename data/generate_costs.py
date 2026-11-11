"""Gera um dataset SINTÉTICO de custos Azure no formato FOCUS 1.0.

Formato de referência (doc oficial Microsoft):
https://learn.microsoft.com/azure/cost-management-billing/dataset-schema/cost-usage-details-focus

Usa um subconjunto das colunas do FOCUS 1.0 (mesmos nomes) e planta anomalias
conhecidas, registradas em `anomalias_esperadas.json` (o "gabarito" da demo).
Nenhum dado aqui é real: assinatura, recursos e valores são fictícios.

Uso:  python data/generate_costs.py
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
START = date(2026, 8, 1)
END = date(2026, 10, 31)          # inclusivo
CURRENCY = "BRL"
USD_RATE = 0.18                    # câmbio fictício BRL -> USD
SUB_ID = "/subscriptions/00000000-0000-0000-0000-000000000000"
SUB_NAME = "sub-demo-automacao"
REGION = ("brazilsouth", "Brazil South")

OUT_DIR = Path(__file__).resolve().parent
CSV_PATH = OUT_DIR / "focus_costs.csv"
GABARITO_PATH = OUT_DIR / "anomalias_esperadas.json"

# nome, resource group, tipo ARM, ServiceName, ServiceCategory, MeterCategory,
# custo diário base (BRL), unidade, preço unitário, fator fim de semana, tags
RESOURCES = [
    ("lgc-desvios-processo", "rg-automacao-prod", "microsoft.logic/workflows", "Logic Apps", "Integration", "Logic Apps", 4.2, "Actions", 0.000125, 0.6, {"owner": "automacao", "env": "prod"}),
    ("lgc-chamados-nao-respondentes", "rg-automacao-prod", "microsoft.logic/workflows", "Logic Apps", "Integration", "Logic Apps", 3.1, "Actions", 0.000125, 0.6, {"owner": "automacao", "env": "prod"}),
    ("lgc-relatorio-custos", "rg-automacao-prod", "microsoft.logic/workflows", "Logic Apps", "Integration", "Logic Apps", 1.4, "Actions", 0.000125, 1.0, {"owner": "automacao", "env": "prod"}),
    ("func-rma-integracao", "rg-automacao-prod", "microsoft.web/sites", "Functions", "Compute", "Functions", 6.5, "Executions", 0.0000011, 0.5, {"owner": "automacao", "env": "prod"}),
    ("func-monitor-custos", "rg-automacao-prod", "microsoft.web/sites", "Functions", "Compute", "Functions", 2.3, "Executions", 0.0000011, 1.0, {"owner": "automacao", "env": "prod"}),
    ("vm-relatorios-dev", "rg-automacao-dev", "microsoft.compute/virtualmachines", "Virtual Machines", "Compute", "Virtual Machines", 18.0, "Hours", 0.75, 1.0, {"owner": "automacao", "env": "dev"}),
    ("vm-jump-admin", "rg-automacao-prod", "microsoft.compute/virtualmachines", "Virtual Machines", "Compute", "Virtual Machines", 9.6, "Hours", 0.40, 1.0, {"owner": "infra", "env": "prod"}),
    ("stgautomacaoprod", "rg-dados", "microsoft.storage/storageaccounts", "Storage", "Storage", "Storage", 5.4, "GB/Month", 0.12, 1.0, {"owner": "automacao", "env": "prod"}),
    ("sqldb-automacao", "rg-dados", "microsoft.sql/servers/databases", "SQL Database", "Databases", "SQL Database", 22.0, "DTU/Day", 1.10, 1.0, {"owner": "automacao", "env": "prod"}),
    ("apim-integracoes", "rg-automacao-prod", "microsoft.apimanagement/service", "API Management", "Integration", "API Management", 31.0, "Units/Day", 31.0, 1.0, {"owner": "automacao", "env": "prod"}),
    ("appi-automacao", "rg-monitoramento", "microsoft.insights/components", "Azure Monitor", "Management and Governance", "Log Analytics", 7.8, "GB", 15.50, 0.7, {"owner": "automacao", "env": "prod"}),
    ("stgbackupantigo", "rg-dados", "microsoft.storage/storageaccounts", "Storage", "Storage", "Storage", 0.0, "GB/Month", 0.12, 1.0, {}),
]

# --- Anomalias plantadas (gabarito) -------------------------------------
ANOMALIAS = [
    {
        "id": "A1", "recurso": "vm-relatorios-dev", "tipo": "pico",
        "inicio": "2026-10-12", "fim": "2026-10-18", "fator": 5.0,
        "historia": "VM de dev redimensionada para um tamanho maior e esquecida ligada por uma semana.",
    },
    {
        "id": "A2", "recurso": "stgbackupantigo", "tipo": "recurso_orfao",
        "inicio": "2026-09-01", "fim": "2026-10-31",
        "historia": "Storage de backup criado sem tag de dono, crescendo todo dia e ninguém usa.",
    },
    {
        "id": "A3", "recurso": "func-rma-integracao", "tipo": "pico",
        "inicio": "2026-10-25", "fim": "2026-10-27", "fator": 12.0,
        "historia": "Function App em loop de retentativas chamando a API externa.",
    },
    {
        "id": "A4", "recurso": "lgc-desvios-processo", "tipo": "mudanca_de_patamar",
        "inicio": "2026-09-15", "fim": "2026-10-31", "fator": 2.2,
        "historia": "Recorrência da Logic App mudou de 1h para 5 min e o custo subiu de patamar.",
    },
]


def iso(d: date) -> str:
    return f"{d.isoformat()}T00:00:00Z"


def month_bounds(d: date):
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt


def in_range(d: date, a: dict) -> bool:
    return date.fromisoformat(a["inicio"]) <= d <= date.fromisoformat(a["fim"])


def daily_cost(name: str, base: float, weekend_factor: float, d: date, rnd: random.Random) -> float:
    cost = base * (weekend_factor if d.weekday() >= 5 else 1.0)
    cost *= rnd.uniform(0.92, 1.08)  # ruído normal
    for a in ANOMALIAS:
        if a["recurso"] != name or not in_range(d, a):
            continue
        if a["tipo"] in ("pico", "mudanca_de_patamar"):
            cost *= a["fator"]
        elif a["tipo"] == "recurso_orfao":
            days = (d - date.fromisoformat(a["inicio"])).days
            cost = 1.5 + 0.35 * days  # cresce todo dia
    return round(cost, 4)


def main():
    rnd = random.Random(SEED)
    cols = [
        "BilledCost", "EffectiveCost", "ListCost", "BillingCurrency",
        "BillingPeriodStart", "BillingPeriodEnd", "ChargeCategory", "ChargeDescription",
        "ChargePeriodStart", "ChargePeriodEnd", "ConsumedQuantity", "ConsumedUnit",
        "PricingCategory", "ProviderName", "PublisherName", "RegionId", "RegionName",
        "ResourceId", "ResourceName", "ResourceType", "ServiceCategory", "ServiceName",
        "SubAccountId", "SubAccountName", "Tags", "x_BilledCostInUsd",
        "x_ResourceGroupName", "x_ResourceType", "x_SkuMeterCategory",
    ]
    rows = []
    d = START
    while d <= END:
        bp_start, bp_end = month_bounds(d)
        for (name, rg, arm_type, svc, cat, meter, base, unit, unit_price, wkd, tags) in RESOURCES:
            orphan = next((a for a in ANOMALIAS if a["recurso"] == name and a["tipo"] == "recurso_orfao"), None)
            if orphan and d < date.fromisoformat(orphan["inicio"]):
                continue  # recurso ainda não existia
            cost = daily_cost(name, base, wkd, d, rnd)
            qty = round(cost / unit_price, 4) if unit_price else 0
            rows.append({
                "BilledCost": cost, "EffectiveCost": cost, "ListCost": round(cost * 1.05, 4),
                "BillingCurrency": CURRENCY,
                "BillingPeriodStart": iso(bp_start), "BillingPeriodEnd": iso(bp_end),
                "ChargeCategory": "Usage", "ChargeDescription": f"{svc} - {meter}",
                "ChargePeriodStart": iso(d), "ChargePeriodEnd": iso(d + timedelta(days=1)),
                "ConsumedQuantity": qty, "ConsumedUnit": unit,
                "PricingCategory": "Standard", "ProviderName": "Microsoft", "PublisherName": "Microsoft",
                "RegionId": REGION[0], "RegionName": REGION[1],
                "ResourceId": f"{SUB_ID}/resourcegroups/{rg}/providers/{arm_type}/{name}",
                "ResourceName": name, "ResourceType": svc, "ServiceCategory": cat, "ServiceName": svc,
                "SubAccountId": SUB_ID, "SubAccountName": SUB_NAME,
                "Tags": json.dumps(tags, ensure_ascii=False),
                "x_BilledCostInUsd": round(cost * USD_RATE, 4),
                "x_ResourceGroupName": rg, "x_ResourceType": arm_type, "x_SkuMeterCategory": meter,
            })
        d += timedelta(days=1)

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    GABARITO_PATH.write_text(json.dumps(ANOMALIAS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(rows)} linhas -> {CSV_PATH.name}; {len(ANOMALIAS)} anomalias -> {GABARITO_PATH.name}")


if __name__ == "__main__":
    main()
