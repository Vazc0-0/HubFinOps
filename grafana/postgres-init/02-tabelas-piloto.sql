-- Tabelas do piloto (Logic App real, histórico e chamados). Também são criadas por tools/carregar_grafana.py,
-- então funcionam mesmo num volume do Postgres que já existia antes desta versão.
CREATE TABLE IF NOT EXISTS azure_execucoes (logic_app text, execucao text PRIMARY KEY, status text,
  inicio timestamptz, fim timestamptz, acoes_total int, acoes_rodaram int, acoes_puladas int,
  acoes_com_falha text, simulada boolean DEFAULT false);
CREATE TABLE IF NOT EXISTS azure_metricas (logic_app text, metrica text, momento timestamptz, total numeric,
  PRIMARY KEY (logic_app, metrica, momento));
CREATE TABLE IF NOT EXISTS azure_precos (medidor text, a_partir_de numeric, preco numeric, unidade text,
  regiao text, moeda text, consultado_em timestamptz);
CREATE TABLE IF NOT EXISTS azure_previsto (logic_app text PRIMARY KEY, previsto_por_execucao numeric,
  fixas int, por_item int, itens_no_loop int, medido_acoes numeric, medido_disparos numeric,
  medido_por_execucao numeric, execucoes_mes numeric, custo_mes_brl numeric);
CREATE TABLE IF NOT EXISTS historico (id text PRIMARY KEY, tarefa text, origem text, status text,
  inicio timestamptz, fim timestamptz, duracao_s numeric, resumo text);
CREATE TABLE IF NOT EXISTS chamados (id text PRIMARY KEY, criado_em timestamptz, titulo text, prioridade text,
  regra text, alvo text, status text, resolvido_em timestamptz);

GRANT SELECT ON azure_execucoes, azure_metricas, azure_precos, azure_previsto, historico, chamados TO grafana_reader;
