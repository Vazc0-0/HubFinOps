# Relatório executivo FinOps: Contoso Produção

Ambiente: **Produção**

> Novembro/2026, dados até 20/11/2026. Gerado em código (tools/finops_tenants.py), sem IA, a partir da exportação FOCUS e do inventário do Azure deste tenant. Dados fictícios de demonstração.

## Em uma linha

O mês deve fechar em **R$ 6.329,97**, dentro do orçamento de R$ 9.000,00 (70,3%). Há **R$ 615,46 por mês** que podem ser economizados agora (R$ 7.385,52 por ano).

## Indicadores

| Indicador | Valor |
|---|---|
| Custo dos últimos 30 dias | R$ 6.349,05 |
| Previsão do mês × orçamento | R$ 6.329,97 × R$ 9.000,00 (70,3%) |
| Economia potencial | R$ 615,46/mês |
| Economia realizada (medida) | R$ 0,00/mês |
| Custo com dono e centro de custo | 96,5% |

## O que fazer agora

| # | Recurso | Problema | Economia/mês | Ação | Dono |
|---|---|---|---|---|---|
| 1 | `vm-erp-conector-prd` | VM superdimensionada: CPU P95 de 14 dias = 11% (limite: 20%), tamanho atual Standard_D8s_v5 | R$ 615,46 | Reduzir um tamanho na mesma família e acompanhar a CPU por 14 dias | integracao |

- **Prestação de contas:** 1 recurso(s) sem dono ou centro de custo (`appi-integracao-prd`). Exigir as tags com Azure Policy.

## Quem gasta (últimos 30 dias)

| Centro de custo | Custo | % |
|---|---|---|
| CC-420 | R$ 4.381,22 | 69,0% |
| CC-410 | R$ 1.742,48 | 27,4% |
| (sem centro de custo) | R$ 225,35 | 3,5% |

## Como os números foram calculados

- Custo: exportação FOCUS do Cost Management (EffectiveCost), só deste tenant.
- Previsão: custo do mês até o corte + média diária dos últimos 7 dias × dias restantes.
- Oportunidades: inventário do Azure Resource Graph (disco Unattached, IP sem associação, snapshot com mais de 90 dias) e CPU P95 de 14 dias do Azure Monitor (abaixo de 20%: estimativa de 50% de economia com um tamanho abaixo).
- Economia realizada: custo diário medido antes e depois de cada ação implementada.
