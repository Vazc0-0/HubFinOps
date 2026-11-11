"""Gera grafana/dashboards/finops-custos.json (dashboard provisionado).

Mantido em Python para ficar fácil de editar; o JSON gerado é o que o Grafana lê.
Uso:  python grafana/build_dashboard.py
"""
import json
from pathlib import Path

DS = {"type": "postgres", "uid": "focus-pg"}
OUT = Path(__file__).resolve().parent / "dashboards" / "finops-custos.json"
_id = 0


def panel(title, ptype, sql, x, y, w, h, fmt="time_series", unit="currencyBRL", options=None, desc="", thresholds=None):
    global _id
    _id += 1
    p = {
        "id": _id, "title": title, "type": ptype, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "datasource": DS, "editorMode": "code", "format": fmt,
                     "rawQuery": True, "rawSql": sql}],
        "fieldConfig": {"defaults": {"unit": unit, "decimals": 0 if unit == "none" else 2,
                                     **({"thresholds": {"mode": "absolute", "steps": thresholds},
                                         "color": {"mode": "thresholds"}} if thresholds else {})},
                        "overrides": []},
        "options": options or {},
    }
    return p


panels = [
    panel("Custo no período", "stat",
          "SELECT sum(billed_cost) AS \"Custo\" FROM focus_costs WHERE $__timeFilter(charge_period_start)",
          0, 0, 6, 4, fmt="table", options={"colorMode": "none", "graphMode": "none"}),
    panel("Custo médio por dia", "stat",
          "SELECT sum(billed_cost) / NULLIF(count(DISTINCT charge_period_start), 0) AS \"Média diária\" "
          "FROM focus_costs WHERE $__timeFilter(charge_period_start)",
          6, 0, 6, 4, fmt="table", options={"colorMode": "none", "graphMode": "none"}),
    panel("Recursos sem dono (sem tag owner)", "stat",
          "SELECT count(DISTINCT resource_name) AS \"Recursos\" FROM focus_costs "
          "WHERE NOT (tags ? 'owner') AND $__timeFilter(charge_period_start)",
          12, 0, 6, 4, fmt="table", unit="none",
          options={"colorMode": "background", "graphMode": "none"},
          desc="Recursos sem responsável tendem a ser esquecidos e gerar custo.",
          thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
    panel("Recursos monitorados", "stat",
          "SELECT count(DISTINCT resource_name) AS \"Recursos\" FROM focus_costs WHERE $__timeFilter(charge_period_start)",
          18, 0, 6, 4, fmt="table", unit="none", options={"colorMode": "none", "graphMode": "none"}),
    panel("Custo diário total", "timeseries",
          "SELECT charge_period_start AS time, sum(billed_cost) AS \"Custo diário\" FROM focus_costs "
          "WHERE $__timeFilter(charge_period_start) GROUP BY 1 ORDER BY 1",
          0, 4, 24, 8),
    panel("Custo diário por recurso", "timeseries",
          "SELECT charge_period_start AS time, resource_name AS metric, sum(billed_cost) AS value FROM focus_costs "
          "WHERE $__timeFilter(charge_period_start) GROUP BY 1, 2 ORDER BY 1",
          0, 12, 24, 10, desc="Picos e mudanças de patamar aparecem aqui."),
    panel("Custo por resource group", "barchart",
          "SELECT x_resource_group_name AS \"Resource group\", sum(billed_cost) AS \"Custo\" FROM focus_costs "
          "WHERE $__timeFilter(charge_period_start) GROUP BY 1 ORDER BY 2 DESC",
          0, 22, 12, 9, fmt="table", options={"orientation": "horizontal", "xField": "Resource group"}),
    panel("Custo por recurso", "table",
          "SELECT resource_name AS \"Recurso\", service_name AS \"Serviço\", x_resource_group_name AS \"Resource group\", "
          "coalesce(tags->>'owner', 'SEM DONO') AS \"Dono\", sum(billed_cost) AS \"Custo\" FROM focus_costs "
          "WHERE $__timeFilter(charge_period_start) GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC",
          12, 22, 12, 9, fmt="table"),
]

dashboard = {
    "uid": "finops-custos-demo",
    "title": "FinOps - Custos Azure (dados sintéticos)",
    "tags": ["finops", "piloto-agentes-ia", "demo"],
    "timezone": "browser",
    "schemaVersion": 39,
    "editable": True,
    "time": {"from": "2026-08-01T00:00:00.000Z", "to": "2026-11-01T00:00:00.000Z"},
    "panels": panels,
}

OUT.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{len(panels)} painéis -> {OUT.name}")
