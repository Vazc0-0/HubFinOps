"""Gera grafana/dashboards/piloto-operacao.json: Logic App real (Azure) + operação do piloto.

Dados carregados por tools/carregar_grafana.py (execuções e métricas do Azure, preços oficiais,
estimativa do leitor, histórico de execuções do piloto e chamados abertos pelos alertas).
Uso:  python grafana/build_dashboard_operacao.py
"""
import json
from pathlib import Path

DS = {"type": "postgres", "uid": "focus-pg"}
OUT = Path(__file__).resolve().parent / "dashboards" / "piloto-operacao.json"
_id = 0


def panel(title, ptype, sql, x, y, w, h, fmt="table", unit="none", decimals=0, options=None, desc="",
          thresholds=None, overrides=None, mappings=None):
    global _id
    _id += 1
    defaults = {"unit": unit, "decimals": decimals}
    if thresholds:
        defaults.update({"thresholds": {"mode": "absolute", "steps": thresholds}, "color": {"mode": "thresholds"}})
    if mappings:
        defaults["mappings"] = mappings
    return {"id": _id, "title": title, "type": ptype, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": "A", "datasource": DS, "editorMode": "code", "format": fmt,
                         "rawQuery": True, "rawSql": sql}],
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
            "options": options or {}}


def row(title, y):
    global _id
    _id += 1
    return {"id": _id, "type": "row", "title": title, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
            "panels": []}


STAT = {"colorMode": "none", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}}
VERDE_VERMELHO = [{"color": "green", "value": None}, {"color": "red", "value": 1}]
STATUS = [{"type": "value", "options": {"Succeeded": {"text": "Sucesso", "color": "green"},
                                       "Failed": {"text": "Falhou", "color": "red"},
                                       "ok": {"text": "OK", "color": "green"},
                                       "falhou": {"text": "Falhou", "color": "red"},
                                       "em andamento": {"text": "Em andamento", "color": "blue"},
                                       "Aberto": {"text": "Aberto", "color": "orange"},
                                       "Resolvido": {"text": "Resolvido", "color": "green"}}}]
COR_STATUS = lambda campo: {"matcher": {"id": "byName", "options": campo},  # noqa: E731
                            "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}}]}

panels = [
    row("Logic App real no Azure (só leitura)", 0),
    panel("Execuções sincronizadas", "stat", "SELECT count(*) AS \"Execuções\" FROM azure_execucoes WHERE NOT simulada",
          0, 1, 4, 4, options=STAT),
    panel("Execuções com falha", "stat", "SELECT count(*) AS \"Falhas\" FROM azure_execucoes WHERE status = 'Failed'",
          4, 1, 4, 4, options={**STAT, "colorMode": "background"}, thresholds=VERDE_VERMELHO,
          desc="Inclui execuções SIMULADAS (carregar_grafana.py --simular-falha). Dispara o alerta e abre chamado."),
    panel("Ações por execução: previsto", "stat",
          "SELECT previsto_por_execucao AS \"Previsto\" FROM azure_previsto LIMIT 1", 8, 1, 4, 4, options=STAT,
          desc="Calculado pelo leitor só lendo o JSON da Logic App (sem executar)."),
    panel("Ações por execução: medido no Azure", "stat",
          "SELECT medido_por_execucao AS \"Medido\" FROM azure_previsto LIMIT 1", 12, 1, 4, 4, decimals=1,
          options=STAT, desc="BillableActionExecutions ÷ BillableTriggerExecutions (Azure Monitor)."),
    panel("Custo estimado por mês", "stat", "SELECT custo_mes_brl AS \"Custo/mês\" FROM azure_previsto LIMIT 1",
          16, 1, 4, 4, unit="currencyBRL", decimals=2, options=STAT,
          desc="Ações nativas além das 4.000 grátis do mês × preço oficial trazido pela própria Logic App."),
    panel("Preço por ação nativa (após a faixa grátis)", "stat",
          "SELECT max(preco) AS \"R$ por ação\" FROM azure_precos WHERE medidor = 'Consumption Built-in Actions'",
          20, 1, 4, 4, unit="currencyBRL", decimals=4, options=STAT),
    panel("Execuções cobradas por dia (Azure Monitor)", "barchart",
          "SELECT to_char(momento, 'DD/MM') AS \"Dia\", "
          "sum(total) FILTER (WHERE metrica = 'BillableActionExecutions') AS \"Ações cobradas\", "
          "sum(total) FILTER (WHERE metrica = 'BillableTriggerExecutions') AS \"Disparos do gatilho\" "
          "FROM azure_metricas GROUP BY momento ORDER BY momento",
          0, 5, 12, 8, options={"xField": "Dia", "legend": {"showLegend": True, "placement": "bottom"}}),
    panel("Últimas execuções", "table",
          "SELECT inicio AS \"Início\", status AS \"Status\", acoes_rodaram AS \"Rodaram\", acoes_puladas AS \"Puladas\", "
          "coalesce(acoes_com_falha, '-') AS \"Ações com falha\", CASE WHEN simulada THEN 'sim' ELSE 'não' END AS \"Simulada\" "
          "FROM azure_execucoes ORDER BY inicio DESC LIMIT 20",
          12, 5, 12, 8, mappings=STATUS, overrides=[COR_STATUS("Status")]),
    panel("Preços oficiais (API de preços do Azure, trazidos pela Logic App)", "table",
          "SELECT medidor AS \"Medidor\", a_partir_de AS \"A partir de\", preco AS \"Preço (R$)\", unidade AS \"Unidade\", "
          "regiao AS \"Região\", consultado_em AS \"Consultado em\" FROM azure_precos ORDER BY medidor, a_partir_de",
          0, 13, 24, 7, decimals=4),
    row("Operação do piloto", 20),
    panel("Execuções registradas", "stat", "SELECT count(*) AS \"Execuções\" FROM historico", 0, 21, 4, 4, options=STAT),
    panel("Execuções com falha", "stat", "SELECT count(*) AS \"Falhas\" FROM historico WHERE status = 'falhou'",
          4, 21, 4, 4, options={**STAT, "colorMode": "background"}, thresholds=VERDE_VERMELHO),
    panel("Chamados abertos", "stat", "SELECT count(*) AS \"Abertos\" FROM chamados WHERE status = 'Aberto'",
          8, 21, 4, 4, options={**STAT, "colorMode": "background"},
          thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}]),
    panel("Chamados resolvidos", "stat", "SELECT count(*) AS \"Resolvidos\" FROM chamados WHERE status = 'Resolvido'",
          12, 21, 4, 4, options=STAT),
    panel("Execuções por tarefa", "barchart",
          "SELECT tarefa AS \"Tarefa\", count(*) FILTER (WHERE status = 'ok') AS \"OK\", "
          "count(*) FILTER (WHERE status = 'falhou') AS \"Falhou\" FROM historico GROUP BY tarefa ORDER BY 2 DESC",
          16, 21, 8, 8, options={"xField": "Tarefa", "orientation": "horizontal", "stacking": "normal"},
          overrides=[{"matcher": {"id": "byName", "options": "OK"},
                      "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
                     {"matcher": {"id": "byName", "options": "Falhou"},
                      "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}]),
    panel("Chamados abertos pelos alertas", "table",
          "SELECT id AS \"Chamado\", criado_em AS \"Aberto em\", prioridade AS \"Prioridade\", titulo AS \"Título\", "
          "status AS \"Status\" FROM chamados ORDER BY criado_em DESC",
          0, 25, 16, 6, mappings=STATUS, overrides=[COR_STATUS("Status")]),
    panel("Histórico de execuções (o mesmo do hub)", "table",
          "SELECT inicio AS \"Início\", tarefa AS \"Tarefa\", origem AS \"Origem\", status AS \"Status\", "
          "duracao_s AS \"Duração (s)\", resumo AS \"Resultado\" FROM historico ORDER BY inicio DESC LIMIT 50",
          0, 31, 24, 10, decimals=1, mappings=STATUS, overrides=[COR_STATUS("Status")]),
]

dashboard = {"uid": "piloto-operacao", "title": "Piloto - Logic App real e operação",
             "tags": ["piloto-agentes-ia", "azure", "operacao"], "timezone": "browser", "schemaVersion": 39,
             "editable": True, "refresh": "30s", "time": {"from": "now-7d", "to": "now"}, "panels": panels}
OUT.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{sum(1 for p in panels if p['type'] != 'row')} painéis -> {OUT.name}")
