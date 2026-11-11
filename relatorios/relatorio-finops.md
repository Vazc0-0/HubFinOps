# Relatório FinOps — 06/11/2026
> Dados sintéticos de demonstração. Números calculados em código e validados automaticamente.
> Gerado em: 06/11/2026 13:47:48

## Resumo
Custo por mês: 08/2026: R$ 3.378,24 | 09/2026: R$ 3.525,60 | 10/2026: R$ 4.762,83.
O último mês variou +35% em relação ao anterior.
Foram encontradas 4 anomalias, que somam R$ 1.615,92 de custo extra; prioridade alta: stgbackupantigo, vm-relatorios-dev.

## Anomalias encontradas
| Recurso | Tipo | Período | Custo extra | Prioridade |
|---|---|---|---|---|
| stgbackupantigo | Recurso sem dono | 01/09 a 31/10 | R$ 732,00 | Alta |
| vm-relatorios-dev | Pico | 12/10 a 18/10 | R$ 513,81 | Alta |
| lgc-desvios-processo | Mudança de patamar | 15/09 a 31/10 | R$ 200,36 | Média |
| func-rma-integracao | Pico | 25/10 a 27/10 | R$ 169,76 | Média |

## O que aconteceu e o que fazer
**stgbackupantigo** (Storage, rg-dados) — Recurso sem dono, de 01/09/2026 a 31/10/2026, custo extra de R$ 732,00 (prioridade alta). O que os dados mostram: sem tag 'owner'; custo foi de R$ 1,50/dia para R$ 22,50/dia. Causa provável: o recurso não tem responsável (sem tag owner) e o custo cresce todo dia. O que fazer: identificar o dono, aplicar a tag owner e avaliar se o recurso pode ser excluído.

**vm-relatorios-dev** (Virtual Machines, rg-automacao-dev) — Pico, de 12/10/2026 a 18/10/2026, custo extra de R$ 513,81 (prioridade alta). O que os dados mostram: até R$ 95,36/dia contra base de R$ 17,90/dia (5.3x). Causa provável: algo ficou ligado ou executando além do normal nesses dias. O que fazer: verificar o que mudou no período, desligar ou redimensionar o recurso e criar um alerta de orçamento.

**lgc-desvios-processo** (Logic Apps, rg-automacao-prod) — Mudança de patamar, de 15/09/2026 a 31/10/2026, custo extra de R$ 200,36 (prioridade média). O que os dados mostram: custo diário típico subiu de R$ 4,02 para R$ 8,97 (2.2x) e não voltou. Causa provável: uma configuração mudou e o custo ficou mais alto de forma permanente. O que fazer: confirmar se a mudança foi intencional (ex.: recorrência mais frequente) e, se não for, reverter.

**func-rma-integracao** (Functions, rg-automacao-prod) — Pico, de 25/10/2026 a 27/10/2026, custo extra de R$ 169,76 (prioridade média). O que os dados mostram: até R$ 76,24/dia contra base de R$ 6,25/dia (12.2x). Causa provável: algo ficou ligado ou executando além do normal nesses dias. O que fazer: verificar o que mudou no período, desligar ou redimensionar o recurso e criar um alerta de orçamento.

## Próximos passos
1. Atacar primeiro as anomalias de prioridade alta.
2. Exigir a tag owner em todos os recursos (Azure Policy) para não surgirem recursos órfãos.
3. Criar alertas de orçamento por resource group para pegar picos no mesmo dia.
