# Relatório executivo FinOps: Fabrikam Saúde

> Novembro/2026, dados até 20/11/2026. Gerado em código (tools/finops_tenants.py), sem IA, a partir da exportação FOCUS e do inventário do Azure deste tenant. Dados fictícios de demonstração.

## Em uma linha

O mês deve fechar em **R$ 6.402,02**, **6,7% acima do orçamento** de R$ 6.000,00. Nenhum desperdício encontrado pelas regras de economia.

## Indicadores

| Indicador | Valor |
|---|---|
| Custo dos últimos 30 dias | R$ 5.530,57 |
| Previsão do mês × orçamento | R$ 6.402,02 × R$ 6.000,00 (106,7%) |
| Economia potencial | R$ 0,00/mês |
| Economia realizada (medida) | R$ 0,00/mês |
| Custo com dono e centro de custo | 95,1% |

## O que fazer agora

- Nenhuma ação de economia pendente pelas regras atuais.

- **Orçamento:** a previsão passa o orçamento em R$ 402,02. A causa é `sqldb-prontuario`: o custo diário subiu de R$ 60,26 para R$ 146,60 (+143%) desde 05/11/2026, cerca de R$ 2.590,18 a mais por mês. Confirmar com o dono se a mudança foi planejada: se foi, ajustar o orçamento; se não, voltar a configuração.

- **Prestação de contas:** 1 recurso(s) sem dono ou centro de custo (`appi-fabrikam`). Exigir as tags com Azure Policy.

## Quem gasta (últimos 30 dias)

| Centro de custo | Custo | % |
|---|---|---|
| CC-10 | R$ 4.725,50 | 85,4% |
| CC-20 | R$ 535,76 | 9,7% |
| (sem centro de custo) | R$ 269,31 | 4,9% |

## Como os números foram calculados

- Custo: exportação FOCUS do Cost Management (EffectiveCost), só deste tenant.
- Previsão: custo do mês até o corte + média diária dos últimos 7 dias × dias restantes.
- Oportunidades: inventário do Azure Resource Graph (disco Unattached, IP sem associação, snapshot com mais de 90 dias) e CPU P95 de 14 dias do Azure Monitor (abaixo de 20%: estimativa de 50% de economia com um tamanho abaixo).
- Economia realizada: custo diário medido antes e depois de cada ação implementada.
