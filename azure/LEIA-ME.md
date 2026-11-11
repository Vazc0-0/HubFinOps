# Logic App de teste no Azure (conta pessoal)

`la-precos-logicapps`: uma Logic App **Consumption** que, uma vez por dia às 08:00, consulta a
[API pública de preços do Azure](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices),
filtra os preços de Logic Apps e monta um resumo. O projeto lê essa Logic App de volta do Azure
(definição, execuções, métricas de cobrança e o resumo de preços) e confere tudo contra o gabarito.

| Arquivo | Para que serve |
|---|---|
| `la-precos-logicapps.json` | Definição para colar no **Modo de exibição de código** do portal |
| `la-precos-logicapps.template.json` | Mesmo fluxo como modelo ARM, para criar pela Azure CLI |
| `../tests/casos_logicapps/fluxo_la_precos.esperado.json` | Gabarito escrito à mão: o que o leitor tem que entender dela |

**Custo:** só usa ações nativas (HTTP, Analisar JSON, Filtrar, Para cada, Condição, Compor, variável).
São cerca de 16 operações por execução, 1 vez por dia: perto de 490 por mês, abaixo das 4.000 ações nativas
grátis por mês da tabela oficial. Sobra só a retenção de dados do histórico, em centavos.

## 0. Antes de começar (Azure for Students)
Assinaturas *Azure for Students* só deixam criar recursos em algumas regiões.
Para ver quais: portal → **Policy** → **Atribuições** → *Allowed resource deployment regions* → valor do parâmetro.
Use uma dessas regiões nos passos abaixo.

## 1A. Criar pelo portal (não precisa instalar nada)
1. Portal do Azure → **Grupos de recursos** → **Criar** → nome `rg-piloto-agentes`, região permitida.
2. Pesquise **Aplicativos lógicos** → **Adicionar** → **Consumo (multilocatário)**.
   Nome `la-precos-logicapps`, grupo `rg-piloto-agentes`, mesma região, *Log Analytics* = **Não** → **Revisar e criar** → **Criar**.
3. **Ir para o recurso** → **Ferramentas de Desenvolvimento** → **Modo de exibição de código**.
   Apague tudo, cole o conteúdo de `la-precos-logicapps.json` e clique em **Salvar**.
4. Para rodar agora sem esperar as 08:00: no **Designer**, clique em **Executar** (ou **Visão geral** → **Executar gatilho**).
   No **Histórico de execuções** deve aparecer **Bem-sucedido**.

## 1B. Ou criar pela Azure CLI
```
az login
az group create --name rg-piloto-agentes --location <região-permitida>
az deployment group create --resource-group rg-piloto-agentes --template-file azure/la-precos-logicapps.template.json
```
Depois rode o gatilho uma vez pelo portal (passo 4 acima).

## 2. Ligar o projeto à Logic App (só leitura)
Precisa da Azure CLI (`winget install --exact --id Microsoft.AzureCLI`, depois feche e abra o terminal).
```
az login
az account show --query id -o tsv
python tools/azure_logicapp.py configurar --assinatura <id-acima> --grupo rg-piloto-agentes --nome la-precos-logicapps
python tools/azure_logicapp.py sincronizar
```
O esperado no fim é **AZURE E LEITURA BATEM**. O comando:
- baixa a definição para `logicapps/reais/la-precos-logicapps.json`;
- lista as últimas execuções e o status de cada ação;
- lê as métricas `BillableActionExecutions` e `BillableTriggerExecutions` (o que o Azure cobrou);
- baixa o resumo de preços da última execução para `relatorios/azure/precos_logicapps.json`;
- compara a estimativa do leitor (ações por execução) com o que o Azure mediu.

Depois:
```
python tests/testar_leitor_logicapps.py      (aparece a parte "10 Logic App real (Azure)")
python tools/doc_logicapp.py gerar           (a página passa a mostrar o custo em R$)
docker agent run agents/documentacao.yaml    (peça: "sincronize com o Azure")
```
As métricas podem levar alguns minutos para aparecer depois da execução.

## 3. Quando terminar
Para parar de rodar: Logic App → **Visão geral** → **Desabilitar**.
Para apagar tudo: `az group delete --name rg-piloto-agentes` (ou excluir o grupo de recursos no portal).

`config/azure.json`, `logicapps/reais/*.json` e `relatorios/azure/` ficam fora do Git.
