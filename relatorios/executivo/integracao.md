# Relatório executivo FinOps: Contoso Integração

Ambiente: **Integração**

> Novembro/2026, dados até 20/11/2026. Gerado em código (tools/finops_tenants.py), sem IA, a partir da exportação FOCUS e do inventário do Azure deste tenant. Dados fictícios de demonstração.

## Em uma linha

O mês deve fechar em **R$ 2.416,38**, dentro do orçamento de R$ 3.600,00 (67,1%). Há **R$ 370,79 por mês** que podem ser economizados agora (R$ 4.449,48 por ano).

## Indicadores

| Indicador | Valor |
|---|---|
| Custo dos últimos 30 dias | R$ 2.417,91 |
| Previsão do mês × orçamento | R$ 2.416,38 × R$ 3.600,00 (67,1%) |
| Economia potencial | R$ 370,79/mês |
| Economia realizada (medida) | R$ 153,27/mês |
| Custo com dono e centro de custo | 95,7% |

## O que fazer agora

| # | Recurso | Problema | Economia/mês | Ação | Dono |
|---|---|---|---|---|---|
| 1 | `vm-hml-01` | VM de não produção ligada 24x7: custa R$ 19,48/dia no fim de semana e R$ 19,12/dia no dia útil (últimos 28 dias): fica ligada 24x7 num ambiente de Integração | R$ 370,79 | Ligar só em horário comercial (auto-shutdown às 19h ou Start/Stop VMs v2 nos dias úteis) | integracao |

- **Prestação de contas:** 1 recurso(s) sem dono ou centro de custo (`stghml`). Exigir as tags com Azure Policy.

## Quem gasta (últimos 30 dias)

| Centro de custo | Custo | % |
|---|---|---|
| CC-420 | R$ 1.773,12 | 73,3% |
| CC-410 | R$ 540,15 | 22,3% |
| (sem centro de custo) | R$ 104,64 | 4,3% |

## Economia já realizada

| Ação | Implementada | Antes (por dia) | Depois (por dia) | Economia/mês |
|---|---|---|---|---|
| Excluir disco gerenciado sem VM (Unattached) (`disk-hml-antigo`) | 14/10/2026 | R$ 5,11 | R$ 0,00 | R$ 153,27 |

## Como os números foram calculados

- Custo: exportação FOCUS do Cost Management (EffectiveCost), só deste tenant.
- Previsão: custo do mês até o corte + média diária dos últimos 7 dias × dias restantes.
- Oportunidades: inventário do Azure Resource Graph (disco Unattached, IP sem associação, snapshot com mais de 90 dias) e CPU P95 de 14 dias do Azure Monitor (abaixo de 20%: estimativa de 50% de economia com um tamanho abaixo).
- VM ligada 24x7 (só fora de produção): custo no fim de semana ≥ 90% do dia útil nos últimos 28 dias; economia estimada ligando 60 das 168 horas da semana.
- Economia realizada: custo diário medido antes e depois de cada ação implementada.
