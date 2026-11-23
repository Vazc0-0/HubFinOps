# Imagem do hub e do receptor de alertas: Python (só biblioteca padrão) + cliente do Postgres (psql),
# usado pela tarefa "Carregar dados no Grafana", + fusos horários (TZ), para os horários saírem no fuso local.
FROM python:3.15-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client tzdata \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
