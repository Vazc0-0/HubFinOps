-- Executado automaticamente pela imagem oficial do Postgres na PRIMEIRA subida
-- (scripts em /docker-entrypoint-initdb.d). Carrega o CSV sintético no formato FOCUS.
CREATE TABLE focus_costs (
  billed_cost            numeric,
  effective_cost         numeric,
  list_cost              numeric,
  billing_currency       text,
  billing_period_start   timestamptz,
  billing_period_end     timestamptz,
  charge_category        text,
  charge_description     text,
  charge_period_start    timestamptz,
  charge_period_end      timestamptz,
  consumed_quantity      numeric,
  consumed_unit          text,
  pricing_category       text,
  provider_name          text,
  publisher_name         text,
  region_id              text,
  region_name            text,
  resource_id            text,
  resource_name          text,
  resource_type          text,
  service_category       text,
  service_name           text,
  sub_account_id         text,
  sub_account_name       text,
  tags                   jsonb,
  x_billed_cost_in_usd   numeric,
  x_resource_group_name  text,
  x_resource_type        text,
  x_sku_meter_category   text
);

COPY focus_costs FROM '/data/focus_costs.csv' WITH (FORMAT csv, HEADER true);

CREATE INDEX ON focus_costs (charge_period_start);
CREATE INDEX ON focus_costs (resource_name);

-- Usuário somente leitura para o Grafana
CREATE ROLE grafana_reader LOGIN PASSWORD 'grafana_reader_demo';
GRANT SELECT ON focus_costs TO grafana_reader;
