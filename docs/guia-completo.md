# Guia completo

Detalhes de cada parte do projeto: arquivos, comandos e gabaritos. Visão geral no [README](../README.md).

Demonstração de uma **equipe de agentes de IA** ([Docker Agent](https://docs.docker.com/ai/docker-agent/))
que analisa custos Azure, encontra anomalias e escreve um relatório, com os dados visíveis no **Grafana**.

> **Todos os dados são sintéticos.** Nenhum dado, nome ou recurso real de empresa é usado.
> O modelo de IA roda localmente (Docker Model Runner): nada sai da máquina.

## Estrutura

| Pasta / arquivo | O que é |
|---|---|
| `data/generate_costs.py` | Gera `focus_costs.csv` no formato **FOCUS 1.0** do Azure Cost Management, com 4 anomalias plantadas |
| `data/anomalias_esperadas.json` | Gabarito: as anomalias que os agentes precisam encontrar |
| `tools/cost_query.py` | Ferramentas (somente leitura) que os agentes usam: `resumo`, `anomalias`, `recurso <nome>` |
| `tools/gerar_relatorio.py` | Gera, salva e valida o relatório (usado pelo agente relator) |
| `tests/validar_gabarito.py` | Confere se a detecção acha exatamente o gabarito |
| `tests/validar_relatorio.py` | Confere se o relatório do agente bate com os dados (pega alucinação) |
| `agents/finops.yaml` | Equipe de agentes: orquestrador → analista de custos → relator |
| `docker-compose.yml` + `grafana/` | Postgres com os dados + Grafana com datasource e dashboard já provisionados |
| `relatorios/` | Onde o agente relator salva o relatório |

## Pré-requisitos

- Docker Desktop 4.63+ (já inclui o Docker Agent): `docker agent version`
- Docker Model Runner ativado (Docker Desktop → Settings → AI): `docker model status`
- Python 3 no PATH: `python --version`

## Passo a passo

Todos os comandos rodam **na raiz do projeto**.

```bash
# 1. Dados sintéticos (já vêm gerados; rode de novo se quiser recriar)
python data/generate_costs.py
python tests/validar_gabarito.py        # deve terminar com "RESULTADO: PASSOU"

# 2. Grafana + Postgres + receptor + hub
python tools/preparar_ambiente.py       # só na primeira vez: cria o .env com o segredo dos alertas
docker compose up -d --build
#    -> http://localhost:3000  (admin / admin)
#    -> Dashboards > Piloto Agentes de IA > "FinOps - Custos Azure (dados sintéticos)"

# 3. Modelo local
docker model pull ai/qwen3
docker agent doctor

# 4. Agentes
docker agent run agents/finops.yaml
#    peça: "Analise os custos e gere o relatório"
#    ou, sem interface:
docker agent run --exec agents/finops.yaml "Analise os custos e gere o relatório"
```

O relatório sai em `relatorios/relatorio-finops.md`. Ele é gerado **por um hook `stop`** do orquestrador
(roda sozinho sempre que o agente termina de responder), então não depende do modelo lembrar de gerar.
Cada execução do hook fica registrada em `relatorios/hook.log`. Confira se o relatório é confiável:

```bash
python tests/validar_relatorio.py      # deve terminar com "RELATÓRIO CONFIÁVEL"
```

### Testar as ferramentas sem gastar modelo

```bash
docker agent debug tool agents/finops.yaml detectar_anomalias --agent analista_custos
```

## Fase 2 — Documentação automática de Logic Apps

Uma equipe de agentes (`agents/documentacao.yaml`) que lê as **definições JSON** das Logic Apps
(formato oficial *Workflow Definition Language*) e gera documentação para o Obsidian, com **diagrama do fluxo
(Mermaid)**, tabela de ações, parâmetros e **achados de boas práticas** (custo, segurança, confiabilidade, manutenção).

| Pasta / arquivo | O que é |
|---|---|
| `logicapps/exemplos/*.json` | 3 Logic Apps **fictícias** no formato oficial, parecidas com automações comuns de um time de integrações |
| `logicapps/achados_esperados.json` | Gabarito: 6 problemas plantados de propósito |
| `tools/doc_logicapp.py` | Lê o JSON e gera `docs/logicapps/*.md` + `INDICE Logic Apps.md` (comandos: `listar`, `resumo`, `achados`, `gerar`) |
| `tests/validar_docs.py` | Reprova documentação com ação inventada, ação faltando, gatilho errado ou achado fora do gabarito |

```bash
python tools/doc_logicapp.py gerar          # gera e valida (deve terminar com "DOCUMENTAÇÃO CONFIÁVEL")
docker agent run agents/documentacao.yaml   # peça: "Documente as Logic Apps" ou "O que a lgc-relatorio-custos faz?"
type docs\logicapps\hook.log               # o hook "stop" registra cada geração automática
```

Achados plantados: recorrência a cada 5 min na `lgc-desvios-processo` (é a causa da mudança de patamar de custo da fase 1),
chave da Function na URL e retentativa desligada na `lgc-relatorio-custos`, e-mail fixo na `lgc-chamados-nao-respondentes`
e falta de tratamento de erro em duas delas.

Referências oficiais: [Workflow Definition Language](https://learn.microsoft.com/azure/logic-apps/workflow-definition-language-schema),
[gatilhos e ações](https://learn.microsoft.com/azure/logic-apps/logic-apps-workflow-actions-triggers),
[tratamento de erros e retentativas](https://learn.microsoft.com/azure/logic-apps/error-exception-handling).

## Leitura exata das Logic Apps (preparação para Logic Apps reais)

A leitura do JSON fica em `tools/logicapp_parser.py`, separada da escrita da página. Para cada ação ela extrai:
ordem real de execução (pelo `runAfter`), bloco e ramo onde está, de onde tira os dados (outras ações, gatilho,
variáveis, parâmetros, item do loop), quem usa o resultado, o que roda em paralelo, configuração do tipo de ação,
retentativa e dados ocultos. Do gatilho, a agenda exata (execuções por dia/semana/mês). Do fluxo, as ações
cobradas por execução (modelo Consumption).

| Arquivo | O que é |
|---|---|
| `tools/logicapp_parser.py` | Leitor determinístico (sem IA) |
| `tests/testar_leitor_logicapps.py` | Bateria de testes: agendas, expressões, gatilhos, 2 fluxos com gabarito escrito à mão, exemplos oficiais da Microsoft, 2.000 fluxos aleatórios com resposta conhecida, mutações e documentação |
| `tests/casos_logicapps/` | Casos e gabaritos usados pela bateria |
| `logicapps/reais/` | Onde colocar o JSON de uma Logic App de verdade (veja o LEIA-ME; os `.json` ficam fora do Git) |

```bash
python tests/testar_leitor_logicapps.py     # deve terminar com "LEITURA 100% CORRETA"
python tools/doc_logicapp.py gerar          # documenta exemplos + reais e valida
```

Limite conhecido: o que um trecho de **JavaScript** (ação *Execute JavaScript Code*) lê de outras ações não é analisado;
a página avisa quando isso acontece.

## Logic App real no Azure (conta pessoal)

`azure/la-precos-logicapps.json` é uma Logic App de teste (só ações nativas, custo perto de zero) que consulta a
API oficial de preços do Azure. `tools/azure_logicapp.py` liga o projeto a ela, **só leitura**, pela Azure CLI:
baixa a definição, as execuções, as métricas de execuções cobradas e o resumo de preços, e confere se o que
rodou no Azure bate com a leitura do JSON. Passo a passo em `azure/LEIA-ME.md`.

```bash
python tools/azure_logicapp.py sincronizar   # termina com "AZURE E LEITURA BATEM" e "Por execução: medido 15 × previsto 15 → BATE"
```

## Hub (tudo numa página)

```bash
python tools/preparar_ambiente.py    # só na primeira vez: cria o .env com o segredo que assina os alertas
docker compose up -d --build         # Postgres + Grafana + receptor + hub (http://localhost:8090)
python tools/carregar_grafana.py     # leva Azure, preços, histórico e chamados para o Grafana (ou pelo hub)
```

O hub mostra, numa página só: o último resultado de cada parte, botões para rodar cada tarefa com o log ao vivo,
o histórico de tudo o que já rodou (hub, terminal, hooks dos agentes e alertas), os resultados (Logic App real,
FinOps, documentação), os chamados abertos pelos alertas, os painéis do Grafana, os métodos de teste e os documentos.
As mesmas tarefas rodam pelo terminal: `python tools/rodar.py tudo` (ou `testes`, `azure`, `grafana`...).
No container, "Sincronizar com o Azure" e "Avaliação dos agentes" aparecem como **Só no PC** (precisam do `az` e do
Docker do PC). Fora do Docker, `python tools/hub.py` continua funcionando como antes.

| Arquivo | O que é |
|---|---|
| `tools/hub.py`, `tools/hub_pagina.html`, `tools/hub_documento.html` | O hub (porta só em 127.0.0.1; só executa pedidos da própria página) |
| `docker/Dockerfile` | Imagem do hub e do receptor: Python + `psql` + fusos horários |
| `tools/preparar_ambiente.py` | Cria o `.env` com o segredo que assina os alertas (`.env.example` mostra o formato) |
| `tools/rodar.py` | Roda as tarefas e grava log + histórico |
| `tools/historico.py` | Histórico único em `relatorios/historico.jsonl` (logs em `relatorios/execucoes/`) |
| `tools/carregar_grafana.py` | Carrega no Postgres: execuções e métricas do Azure, preços, previsto × medido, histórico, chamados |
| `grafana/dashboards/piloto-operacao.json` | Painel "Logic App real e operação do piloto" (gerado por `grafana/build_dashboard_operacao.py`) |
| `grafana/provisioning/alerting/piloto-alertas.yaml` | 3 alertas: recurso sem dono, Logic App com falha, custo medido ≠ previsto |
| `tools/receptor_chamados.py` | Recebe os alertas do Grafana (webhook **assinado com HMAC-SHA256**) e abre chamados com diagnóstico em `chamados/` |
| `tests/testar_chamados.py` | Testa o receptor com alertas reais do Grafana (`tests/casos_chamados/`) e a assinatura (sem, errada, alterada, velha) |

Para testar o alerta de falha sem quebrar a Logic App: `python tools/carregar_grafana.py --simular-falha`
(abre um chamado em ~1 minuto) e depois `--limpar-simulacao` (o chamado é marcado como resolvido).

## As anomalias plantadas (gabarito)

| ID | Recurso | Tipo | Período | História |
|---|---|---|---|---|
| A1 | vm-relatorios-dev | pico (5x) | 12 a 18/10 | VM de dev redimensionada e esquecida ligada |
| A2 | stgbackupantigo | recurso órfão | desde 01/09 | Storage sem tag de dono crescendo todo dia |
| A3 | func-rma-integracao | pico (12x) | 25 a 27/10 | Function App em loop de retentativas |
| A4 | lgc-desvios-processo | mudança de patamar (2,2x) | desde 15/09 | Recorrência mudou de 1 h para 5 min |

## Por que o relatório é gerado em código

Nos testes com o modelo local (qwen3), o agente relator **inventou recursos e valores** e, depois, **disse que salvou o arquivo sem salvar**. Por isso, números e gravação ficam em código determinístico e todo relatório passa pelo `validar_relatorio.py`. Os agentes coordenam, consultam e explicam. Com um modelo maior (ex.: Azure OpenAI via APIM), dá para devolver a redação ao agente mantendo o validador.

## Observações

- Se regerar o CSV, recarregue o banco: `docker compose down -v && docker compose up -d`.
- O dashboard é gerado por `grafana/build_dashboard.py` (edite o Python e rode de novo).
- Senhas do `docker-compose.yml` são só para a demo local.

## Fontes oficiais

- Docker Agent: https://docs.docker.com/ai/docker-agent/
- Docker Model Runner (provider dmr): https://docs.docker.com/ai/docker-agent/providers/dmr/
- Ferramenta script: https://docs.docker.com/ai/docker-agent/tools/script/
- Esquema FOCUS do Azure: https://learn.microsoft.com/azure/cost-management-billing/dataset-schema/cost-usage-details-focus
- Alertas do Grafana por arquivo (provisioning): https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/
- Webhook do Grafana (formato do alerta): https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/
- Métricas da Logic App (Azure Monitor): https://learn.microsoft.com/azure/logic-apps/monitor-logic-apps-reference#metrics
- Datasource PostgreSQL no Grafana: https://grafana.com/docs/grafana/v12.4/datasources/postgres/configure/
