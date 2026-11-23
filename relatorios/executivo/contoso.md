# Relatório executivo FinOps: Contoso Varejo

> Novembro/2026, dados até 20/11/2026. Gerado em código (tools/finops_tenants.py), sem IA, a partir da exportação FOCUS e do inventário do Azure deste tenant. Dados fictícios de demonstração.

## Em uma linha

O mês deve fechar em **R$ 8.725,94**, dentro do orçamento de R$ 9.500,00 (91,9%). Há **R$ 1.396,83 por mês** que podem ser economizados agora (R$ 16.761,96 por ano).

## Indicadores

| Indicador | Valor |
|---|---|
| Custo dos últimos 30 dias | R$ 8.726,44 |
| Previsão do mês × orçamento | R$ 8.725,94 × R$ 9.500,00 (91,9%) |
| Economia potencial | R$ 1.396,83/mês |
| Economia realizada (medida) | R$ 0,00/mês |
| Custo com dono e centro de custo | 99,7% |

## O que fazer agora

| # | Recurso | Problema | Economia/mês | Ação | Dono |
|---|---|---|---|---|---|
| 1 | `vm-relatorios-02` | VM superdimensionada: CPU P95 de 14 dias = 9% (limite: 20%), tamanho atual Standard_D16s_v5 | R$ 1.142,17 | Reduzir um tamanho na mesma família e acompanhar a CPU por 14 dias | bi |
| 2 | `disk-backup-01` | Disco sem VM (órfão): diskState = Unattached (nenhuma VM usa o disco) | R$ 148,25 | Excluir o disco (fazer um snapshot antes, se houver dúvida) | loja |
| 3 | `snap-vm-pdv-2025-12` | Snapshot antigo: criado há 345 dias (limite: 90) | R$ 77,68 | Excluir o snapshot ou mover para camada de arquivamento, conforme a política de retenção | loja |
| 4 | `pip-legado-01` | IP público sem uso: sem ipConfiguration (não está associado a nada) | R$ 28,73 | Excluir o IP público não associado | (sem dono) |

- **Prestação de contas:** 1 recurso(s) sem dono ou centro de custo (`pip-legado-01`). Exigir as tags com Azure Policy.

## Quem gasta (últimos 30 dias)

| Centro de custo | Custo | % |
|---|---|---|
| CC-100 | R$ 3.178,93 | 36,4% |
| CC-300 | R$ 2.860,13 | 32,8% |
| CC-200 | R$ 2.658,65 | 30,5% |
| (sem centro de custo) | R$ 28,73 | 0,3% |

## Como os números foram calculados

- Custo: exportação FOCUS do Cost Management (EffectiveCost), só deste tenant.
- Previsão: custo do mês até o corte + média diária dos últimos 7 dias × dias restantes.
- Oportunidades: inventário do Azure Resource Graph (disco Unattached, IP sem associação, snapshot com mais de 90 dias) e CPU P95 de 14 dias do Azure Monitor (abaixo de 20%: estimativa de 50% de economia com um tamanho abaixo).
- Economia realizada: custo diário medido antes e depois de cada ação implementada.
