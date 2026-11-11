# Logic Apps reais

Coloque aqui o JSON de uma Logic App de verdade, um arquivo por fluxo (`nome-do-fluxo.json`).
O leitor documenta esta pasta junto com `logicapps/exemplos`.

## Como copiar o JSON do portal (só leitura)

Passos da documentação oficial
([Handle errors — code view](https://learn.microsoft.com/azure/logic-apps/error-exception-handling#change-run-after-behavior-in-the-code-view-editor)):

- **Consumption:** abra a Logic App no portal do Azure → **Ferramentas de Desenvolvimento** → **Modo de exibição de código**.
- **Standard:** **Fluxos de trabalho** → escolha o fluxo → **Ferramentas** → **Código**.

Selecione tudo, copie e salve como `.json` nesta pasta. Não precisa alterar nada no fluxo.

## Antes de salvar

- Se aparecer chave, senha ou token escrito direto no JSON, troque por `REMOVIDO`.
  (O leitor também aponta isso como achado e a documentação esconde o valor, mas é melhor não guardar.)
- Os arquivos `.json` desta pasta ficam fora do Git (`.gitignore`): não vão para o repositório.

## Depois

```
python tools/doc_logicapp.py gerar
python tests/validar_docs.py
```
A página sai em `docs/logicapps/<nome>.md`.
