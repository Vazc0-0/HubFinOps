---
type: nota
tags: [documentacao, logic-apps, gerado-automaticamente]
area: projetos
created: 2026-11-25
updated: 2026-11-25
---
# Documentação — lgc-chamados-nao-respondentes
> Gerada automaticamente a partir de `logicapps/exemplos/lgc-chamados-nao-respondentes.json` em 25/11/2026 10:17:36. Conteúdo extraído do JSON por código (tools/logicapp_parser.py) e conferido por `tests/validar_docs.py`. Exemplo fictício.

## Resumo
Roda todo mês, às 09:00 (no dia 1) — fuso E. South America Standard Time. Usa Excel Online (Business), Office 365 Outlook. Tem 7 ações e trata erros. Achados de boas práticas: **1**.

## Gatilho
| Nome | Tipo | Quando roda | Execuções/dia | Execuções/mês |
|---|---|---|---|---|
| Recorrencia_mensal | Recorrência | todo mês, às 09:00 (no dia 1) — fuso E. South America Standard Time | 0,03 | 1 |

## Fluxo
```mermaid
flowchart TD
    T(["⏰ Recorrencia_mensal<br/>todo mês, às 09:00 (no dia 1) — fuso E. South America Standa"])
    subgraph n1["1. Escopo (bloco): Tentar"]
        n1_1["1.1. Ler_planilha_de_chamados<br/><small>Excel Online (Business)</small>"]
        n1_2["1.2. Filtrar_nao_respondidos<br/><small>Filtrar matriz</small>"]
        n1_3["1.3. Montar_top_5<br/><small>Compor</small>"]
        n1_4["1.4. Tabela_top_5<br/><small>Tabela HTML/CSV</small>"]
        n1_5["1.5. Enviar_ranking_ao_coordenador<br/><small>Office 365 Outlook</small>"]
    end
    n2["2. Avisar_falha<br/><small>Office 365 Outlook</small>"]
    T --> n1
    n1_1 --> n1_2
    n1_2 --> n1_3
    n1_3 --> n1_4
    n1_4 --> n1_5
    n1 -.->|falhar / esgotar o tempo| n2
```

## Passo a passo
Ordem de execução lida do JSON. Números como `3.S.1` indicam: passo 3, ramo **S**im, 1ª ação do ramo (`N` = Não, `P` = Padrão, ou o nome do caso no Switch).

### 1. Tentar — Escopo (bloco)
- **O que faz:** Agrupa as ações de dentro. O resultado do bloco (sucesso ou falha) pode disparar ações seguintes.
- **Quando roda:** logo no início, quando o gatilho dispara.
- **Quem usa o resultado:** `Avisar_falha`

#### 1.1. Ler_planilha_de_chamados — Conector gerenciado
- **O que faz:** Usa o conector **Excel Online (Business)** para: Obter itens da tabela 'Tabela1'.
- **Quando roda:** no início do bloco `Tentar`.
- **Dentro de:** `Tentar`
- **Quem usa o resultado:** `Filtrar_nao_respondidos`

#### 1.2. Filtrar_nao_respondidos — Filtrar matriz
- **O que faz:** Filtra a lista `@body('Ler_planilha_de_chamados')?['value']` mantendo os itens em que `@equals(item()?['Respondido'], 'Nao')`.
- **Quando roda:** depois que `Ler_planilha_de_chamados` terminar com sucesso.
- **Dentro de:** `Tentar`
- **Usa dados de:** saída de `Ler_planilha_de_chamados`, cada item da própria lista
- **Quem usa o resultado:** `Montar_top_5`

#### 1.3. Montar_top_5 — Compor
- **O que faz:** Monta um valor a partir de: `@take(body('Filtrar_nao_respondidos'), 5)`.
- **Quando roda:** depois que `Filtrar_nao_respondidos` terminar com sucesso.
- **Dentro de:** `Tentar`
- **Usa dados de:** saída de `Filtrar_nao_respondidos`
- **Quem usa o resultado:** `Tabela_top_5`

#### 1.4. Tabela_top_5 — Tabela HTML/CSV
- **O que faz:** Cria uma tabela HTML a partir de `@outputs('Montar_top_5')` (colunas: automáticas).
- **Quando roda:** depois que `Montar_top_5` terminar com sucesso.
- **Dentro de:** `Tentar`
- **Usa dados de:** saída de `Montar_top_5`
- **Quem usa o resultado:** `Enviar_ranking_ao_coordenador`

#### 1.5. Enviar_ranking_ao_coordenador — Conector gerenciado
- **O que faz:** Usa o conector **Office 365 Outlook** para: Enviar um e-mail (V2). Para: `coordenador@empresa-exemplo.com`; assunto: “Top 5 — chamados não respondidos no mês”.
- **Quando roda:** depois que `Tabela_top_5` terminar com sucesso.
- **Dentro de:** `Tentar`
- **Usa dados de:** saída de `Tabela_top_5`

### 2. Avisar_falha — Conector gerenciado
- **O que faz:** Usa o conector **Office 365 Outlook** para: Enviar um e-mail (V2). Para: `@{parameters('emailSuporte')}`; assunto: “Falha na automação de chamados”.
- **Quando roda:** depois que `Tentar` falhar ou esgotar o tempo.
- **Usa dados de:** saída de `Tentar`, parâmetro `emailSuporte`

## Parâmetros
| Nome | Tipo | Valor padrão |
|---|---|---|
| siteUrl | String | https://exemplo.sharepoint.com/sites/demo |
| emailSuporte | String | suporte-automacao@empresa-exemplo.com |

## Custo (execuções cobradas)
No plano Consumption, cada execução de gatilho e de ação é medida; dentro de loop, cada volta conta ([Microsoft Learn](https://learn.microsoft.com/azure/logic-apps/logic-apps-pricing)).

| Item | Valor |
|---|---|
| Ações por execução (fora de loops; em condições, o ramo mais longo) | 6 (conector gerenciado: 2) |
| Só rodam se algo falhar (não entram na conta) | Avisar_falha |
| Execuções do gatilho por mês | 1 |
| Ações fixas por mês (execuções × ações fixas) | 6 |

## Conexões
Conexões são recursos separados no Azure (Microsoft.Web/connections); uma conexão com erro derruba todas as ações que a usam ([Microsoft Learn](https://learn.microsoft.com/azure/logic-apps/manage-logic-apps-with-azure-portal#view-connections)).

| Chave no fluxo | Serviço | Recurso de conexão | Ações que usam | Status | Também usada por |
|---|---|---|---|---|---|
| excelonlinebusiness | Excel Online (Business) | excelonlinebusiness | Ler_planilha_de_chamados | Connected | - |
| office365 | Office 365 Outlook | office365 | Enviar_ranking_ao_coordenador, Avisar_falha | Connected | [[lgc-desvios-processo]], [[lgc-relatorio-custos]] |

## Dependências
O fluxo precisa destes serviços de pé:

- `Ler_planilha_de_chamados` → conector Excel Online (Business) (conexão `excelonlinebusiness`)
- `Enviar_ranking_ao_coordenador` → conector Office 365 Outlook (conexão `office365`)
- `Avisar_falha` → conector Office 365 Outlook (conexão `office365`)

## Tratamento de erro
- `Avisar_falha` roda se `Tentar` falhar ou esgotar o tempo (cobre 6 ação(ões): Enviar_ranking_ao_coordenador, Filtrar_nao_respondidos, Ler_planilha_de_chamados, Montar_top_5, Tabela_top_5, Tentar).
- Retentativa: todas as ações usam a política padrão (até 4 novas tentativas em erros 408, 429 e 5xx).
- Referência: [tratar erros e exceções](https://learn.microsoft.com/azure/logic-apps/error-exception-handling).

## Runbook: quando falhar
1. **Ver o erro:** portal do Azure > Logic App `lgc-chamados-nao-respondentes` > Visão geral (Overview) > Histórico de execuções (Runs history) > abrir a execução com falha. A ação em vermelho mostra o código e a mensagem ([Microsoft Learn](https://learn.microsoft.com/azure/logic-apps/view-workflow-status-run-history)).
2. **Identificar a causa pelo código:**
   - **401/403 (não autorizado/proibido):** conexão expirada ou sem permissão. Logic App > Conexões de API (API connections) > a conexão > Editar conexão de API (Edit API connection) > autorizar de novo com a conta certa. Conexões deste fluxo: Excel Online (Business), Office 365 Outlook.
   - **404 (não encontrado):** lista, arquivo, caixa ou endereço foi renomeado ou apagado; ajustar a ação.
   - **408, 429 ou 5xx (passageiro):** costuma resolver sozinho; com a retentativa padrão o Azure tenta de novo até 4 vezes.
   - Pontos que dependem de fora (os primeiros a conferir): `Ler_planilha_de_chamados` (conector Excel Online (Business) (conexão `excelonlinebusiness`)); `Enviar_ranking_ao_coordenador` (conector Office 365 Outlook (conexão `office365`)); `Avisar_falha` (conector Office 365 Outlook (conexão `office365`)).
3. **Reenviar depois de corrigir:** na execução com falha, **Reenviar** (Resubmit) roda o fluxo inteiro de novo com as mesmas entradas e a mesma versão do fluxo, ou **Enviar a partir desta ação** (Submit from this action) para recomeçar do ponto da falha (não vale para ações dentro de loops e de ramos de condição).
   - **Cuidado, reenviar repete:** `Enviar_ranking_ao_coordenador` (Office 365 Outlook (POST)); `Avisar_falha` (Office 365 Outlook (POST)). Confira se isso já aconteceu na execução que falhou para não duplicar.
4. **Quem acionar:** a Logic App não tem dono definido (tag owner); defina um antes de precisar.

### Situação atual (dados de operação fictícios)
- **Atenção** · 1 execução(ões) nos últimos 30 dias, 0 com falha · última em 01/11/2026 (Succeeded).
- SEM_DONO (Média): tag owner ausente

## Ações
| # | Ação | Tipo | Conector | Dentro de | Executa após |
|---|---|---|---|---|---|
| 1 | Tentar | Escopo (bloco) | - | - | início do bloco |
| 1.1 | Ler_planilha_de_chamados | Conector gerenciado | Excel Online (Business) | Tentar | início do bloco |
| 1.2 | Filtrar_nao_respondidos | Filtrar matriz | - | Tentar | Ler_planilha_de_chamados (Succeeded) |
| 1.3 | Montar_top_5 | Compor | - | Tentar | Filtrar_nao_respondidos (Succeeded) |
| 1.4 | Tabela_top_5 | Tabela HTML/CSV | - | Tentar | Montar_top_5 (Succeeded) |
| 1.5 | Enviar_ranking_ao_coordenador | Conector gerenciado | Office 365 Outlook | Tentar | Tabela_top_5 (Succeeded) |
| 2 | Avisar_falha | Conector gerenciado | Office 365 Outlook | - | Tentar (Failed, TimedOut) |

## Achados de boas práticas
| Severidade | Regra | Categoria | Onde | Detalhe | Recomendação |
|---|---|---|---|---|---|
| Baixa | DESTINATARIO_FIXO | Manutenção | Enviar_ranking_ao_coordenador | Endereço de e-mail escrito direto na ação. (To: coordenador@empresa-exemplo.com) | Mover o destinatário para um parâmetro do fluxo (ou lista no SharePoint). |

---
↩︎ [[INDICE Logic Apps]]
