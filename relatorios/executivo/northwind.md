# Relatório executivo FinOps: Northwind Logística

> Novembro/2026, dados até 20/11/2026. Gerado em código (tools/finops_tenants.py), sem IA, a partir da exportação FOCUS e do inventário do Azure deste tenant. Dados fictícios de demonstração.

## Em uma linha

O mês deve fechar em **R$ 2.294,07**, dentro do orçamento de R$ 3.200,00 (71,7%). Há **R$ 479,96 por mês** que podem ser economizados agora (R$ 5.759,52 por ano).

## Indicadores

| Indicador | Valor |
|---|---|
| Custo dos últimos 30 dias | R$ 2.309,62 |
| Previsão do mês × orçamento | R$ 2.294,07 × R$ 3.200,00 (71,7%) |
| Economia potencial | R$ 479,96/mês |
| Economia realizada (medida) | R$ 185,01/mês |
| Custo com dono e centro de custo | 92,2% |

## O que fazer agora

| # | Recurso | Problema | Economia/mês | Ação | Dono |
|---|---|---|---|---|---|
| 1 | `vm-rotas-01` | VM superdimensionada: CPU P95 de 14 dias = 15% (limite: 20%), tamanho atual Standard_D8s_v5 | R$ 451,42 | Reduzir um tamanho na mesma família e acompanhar a CPU por 14 dias | operacoes |
| 2 | `pip-sem-uso-03` | IP público sem uso: sem ipConfiguration (não está associado a nada) | R$ 28,54 | Excluir o IP público não associado | operacoes |

- **Prestação de contas:** 1 recurso(s) sem dono ou centro de custo (`stgnorthwindlogs`). Exigir as tags com Azure Policy.

## Quem gasta (últimos 30 dias)

| Centro de custo | Custo | % |
|---|---|---|
| CC-7 | R$ 2.129,99 | 92,2% |
| (sem centro de custo) | R$ 179,63 | 7,8% |

## Economia já realizada

| Ação | Implementada | Antes (por dia) | Depois (por dia) | Economia/mês |
|---|---|---|---|---|
| Excluir disco gerenciado sem VM (Unattached) (`disk-antigo-02`) | 10/10/2026 | R$ 6,17 | R$ 0,00 | R$ 185,01 |

## Como os números foram calculados

- Custo: exportação FOCUS do Cost Management (EffectiveCost), só deste tenant.
- Previsão: custo do mês até o corte + média diária dos últimos 7 dias × dias restantes.
- Oportunidades: inventário do Azure Resource Graph (disco Unattached, IP sem associação, snapshot com mais de 90 dias) e CPU P95 de 14 dias do Azure Monitor (abaixo de 20%: estimativa de 50% de economia com um tamanho abaixo).
- Economia realizada: custo diário medido antes e depois de cada ação implementada.
