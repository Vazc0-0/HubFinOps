# Comparação de versões: lgc-desvios-processo

> Gerado automaticamente em código (tools/comparar_logicapp.py), sem IA. Versão anterior: logicapps/versoes/lgc-desvios-processo.v1.json; atual: logicapps/exemplos/lgc-desvios-processo.json. É a mudança por trás da anomalia A4 dos dados de custo (mudança de patamar desde 15/09).

| | Antes | Depois |
|---|---|---|
| Versão | v1 (fictícia) | atual |
| Alterada em | 2026-09-14 18:00:00 | – |

## Resumo

- Ações: 5 → 5 (0 nova(s), 0 removida(s), 0 alterada(s)).
- Gatilho: a cada hora — fuso E. South America Standard Time → **a cada 5 minutos — fuso E. South America Standard Time**.
- Execuções por mês: 730 → **8.760**.
- Riscos: 1 novo(s), 0 resolvido(s).

## Pontos de atenção

- Ações cobradas por mês sobem 1100% (1.460 → 17.520): confirmar se a mudança foi intencional.
- Risco novo (Média): RECORRENCIA_FREQUENTE em `Recorrencia` (288 execuções por dia).

## Custo previsto

| Item | Antes | Depois |
|---|---|---|
| Execuções do gatilho por mês | 730 | 8.760 |
| Ações cobradas por execução (fora de loops) | 2 | 2 |
| Ações fixas por mês | 1.460 | 17.520 |
| Ações a cada item de `Para_cada_analista` | 3 | 3 |

## Ações

Nenhuma ação mudou.

## Riscos de boas práticas

**Apareceram**

| Severidade | Achado | Onde | Recomendação |
|---|---|---|---|
| Média | RECORRENCIA_FREQUENTE (288 execuções por dia) | `Recorrencia` | Ajustar a recorrência à necessidade real (ex.: relatório semanal → 1x por semana). |

## Fontes oficiais

- [Workflow Definition Language](https://learn.microsoft.com/azure/logic-apps/workflow-definition-language-schema)
- [Cobrança das Logic Apps (Consumo)](https://learn.microsoft.com/azure/logic-apps/logic-apps-pricing)
- [Versões de uma Logic App (REST)](https://learn.microsoft.com/rest/api/logic/workflow-versions/list)
