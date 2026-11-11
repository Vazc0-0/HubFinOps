# Relatório FinOps — 2026-11-03
> Dados sintéticos de demonstração.
## Resumo (3 linhas)
1. Custo total do mês foi de R$ 50.000,00, com variação de 15% em relação ao mês anterior.
2. Identificadas 3 anomalias com possíveis otimizações de custo.
3. Recomenda-se revisão de recursos em uso e ajustes na infraestrutura.
## Anomalias encontradas (uma tabela: Recurso | Tipo | Período | Custo extra | Prioridade)
| Recurso        | Tipo       | Período   | Custo extra  | Prioridade |
|----------------|------------|-----------|--------------|------------|
| db-prod        | Banco de Dados | Outubro   | R$ 1.200,00  | Alta       |
| ec2-us-east-1  | Servidor   | Setembro  | R$ 850,00    | Média      |
| s3-bucket-01   | Armazenamento | Outubro   | R$ 950,00    | Alta       |
## O que aconteceu e o que fazer (um parágrafo curto por anomalia)
A instância db-prod teve custo extra devido a uso excessivo de CPU. Recomenda-se reavaliar o plano de escalabilidade ou migrar para um plano mais eficiente.
O ec2-us-east-1 apresentou custo acima do esperado por inatividade prolongada. É necessário desligar ou reconfigurar a instância para evitar custos desnecessários.
O bucket s3-bucket-01 tem custo extra por armazenamento redundante. Deve-se verificar a necessidade de redundância e ajustar o plano de armazenamento.
## Próximos passos
Revisar recursos não otimizados, avaliar alternativas de infraestrutura e implementar monitoramento contínuo de custos.