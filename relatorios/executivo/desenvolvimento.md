# Relatório executivo FinOps: Contoso Desenvolvimento

Ambiente: **Desenvolvimento**

> Novembro/2026, dados até 20/11/2026. Gerado em código (tools/finops_tenants.py), sem IA, a partir da exportação FOCUS e do inventário do Azure deste tenant. Dados fictícios de demonstração.

## Em uma linha

O mês deve fechar em **R$ 3.794,69**, **18,6% acima do orçamento** de R$ 3.200,00. Há **R$ 1.325,07 por mês** que podem ser economizados agora (R$ 15.900,84 por ano).

## Indicadores

| Indicador | Valor |
|---|---|
| Custo dos últimos 30 dias | R$ 3.013,50 |
| Previsão do mês × orçamento | R$ 3.794,69 × R$ 3.200,00 (118,6%) |
| Economia potencial | R$ 1.325,07/mês |
| Economia realizada (medida) | R$ 0,00/mês |
| Custo com dono e centro de custo | 99,1% |

## O que fazer agora

| # | Recurso | Problema | Economia/mês | Ação | Dono |
|---|---|---|---|---|---|
| 1 | `vm-carga-dev` | VM de não produção ligada 24x7: custa R$ 77,43/dia no fim de semana e R$ 76,41/dia no dia útil (últimos 28 dias): fica ligada 24x7 num ambiente de Desenvolvimento | R$ 739,41 | Ligar só em horário comercial (auto-shutdown às 19h ou Start/Stop VMs v2 nos dias úteis) | integracao |
| 2 | `vm-build-dev` | VM de não produção ligada 24x7: custa R$ 19,36/dia no fim de semana e R$ 19,17/dia no dia útil (últimos 28 dias): fica ligada 24x7 num ambiente de Desenvolvimento | R$ 370,43 | Ligar só em horário comercial (auto-shutdown às 19h ou Start/Stop VMs v2 nos dias úteis) | integracao |
| 3 | `disk-dados-01` | Disco sem VM (órfão): diskState = Unattached (nenhuma VM usa o disco) | R$ 114,00 | Excluir o disco (fazer um snapshot antes, se houver dúvida) | integracao |
| 4 | `snap-build-dev-2026-03` | Snapshot antigo: criado há 250 dias (limite: 90) | R$ 72,75 | Excluir o snapshot ou mover para camada de arquivamento, conforme a política de retenção | integracao |
| 5 | `pip-teste-dev` | IP público sem uso: sem ipConfiguration (não está associado a nada) | R$ 28,48 | Excluir o IP público não associado | (sem dono) |

- **Orçamento:** a previsão passa o orçamento em R$ 594,69. A causa: `vm-carga-dev` é um recurso novo (desde 06/11/2026) que custa R$ 78,42/dia, cerca de R$ 2.352,46 por mês. Confirmar com o dono se foi planejado: se foi, ajustar o orçamento; se não, desligar ou voltar a configuração.

- **Prestação de contas:** 1 recurso(s) sem dono ou centro de custo (`pip-teste-dev`). Exigir as tags com Azure Policy.

## Quem gasta (últimos 30 dias)

| Centro de custo | Custo | % |
|---|---|---|
| CC-410 | R$ 2.336,04 | 77,5% |
| CC-430 | R$ 648,98 | 21,5% |
| (sem centro de custo) | R$ 28,48 | 0,9% |

## Como os números foram calculados

- Custo: exportação FOCUS do Cost Management (EffectiveCost), só deste tenant.
- Previsão: custo do mês até o corte + média diária dos últimos 7 dias × dias restantes.
- Oportunidades: inventário do Azure Resource Graph (disco Unattached, IP sem associação, snapshot com mais de 90 dias) e CPU P95 de 14 dias do Azure Monitor (abaixo de 20%: estimativa de 50% de economia com um tamanho abaixo).
- VM ligada 24x7 (só fora de produção): custo no fim de semana ≥ 90% do dia útil nos últimos 28 dias; economia estimada ligando 60 das 168 horas da semana.
- Economia realizada: custo diário medido antes e depois de cada ação implementada.
