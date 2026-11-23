# Relatório executivo FinOps: visão consolidada da empresa

> Dados até 20/11/2026. Uso do time de FinOps e da gestão: cada time recebe o relatório do seu ambiente, que só mostra o próprio tenant. Gerado em código, dados fictícios.

| Tenant | Custo 30 dias | Previsão × orçamento | Economia potencial/mês | Economia realizada/mês | Tags |
|---|---|---|---|---|---|
| [Contoso Produção](producao.md) | R$ 6.349,05 | 70,3% | R$ 615,46 | R$ 0,00 | 96,5% |
| [Contoso Desenvolvimento](desenvolvimento.md) | R$ 3.013,50 | 118,6% ⚠️ | R$ 1.325,07 | R$ 0,00 | 99,1% |
| [Contoso Integração](integracao.md) | R$ 2.417,91 | 67,1% | R$ 370,79 | R$ 153,27 | 95,7% |

**Economia potencial somada:** R$ 2.311,32/mês (R$ 27.735,84/ano). **Realizada:** R$ 153,27/mês.

## Quanto custa o que não é produção

Desenvolvimento + integração custaram **R$ 5.431,41** em 30 dias: **85,5% do custo de produção**.

| App | Produção | Fora de produção | Fora ÷ produção |
|---|---|---|---|
| integracao-erp | R$ 4.381,22 | R$ 1.773,12 | 40,5% |
| pedidos | R$ 1.742,48 | R$ 2.876,19 | 165,1% ⚠️ |
| pipeline | R$ 0,00 | R$ 648,98 | só fora de produção |

⚠️ = o app custa fora de produção 50% ou mais do que em produção: rever o tamanho dos bancos e VMs de dev/integração e desligar fora do horário comercial.
