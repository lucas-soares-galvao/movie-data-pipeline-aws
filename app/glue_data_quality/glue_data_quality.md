# glue_data_quality — Validador de Qualidade de Dados

## O que é

O Glue Data Quality é um job transversal do pipeline: é acionado pelo Glue ETL, pelo Glue Details e pelo Glue AGG após cada tabela ser gravada nas camadas SOT e SPEC (para entender essas camadas, veja a seção "Camadas de dados" no README). Ele avalia regras de qualidade de dados usando **DQDL** (Data Quality Definition Language — linguagem específica do AWS Glue para definir regras como "a coluna id nunca pode ser nula") contra as tabelas processadas, salva os resultados na camada **DQ** e envia notificações por e-mail via **SNS** (Simple Notification Service — serviço de notificações da AWS) caso alguma regra falhe.

## Por que existe

Garante que dados problemáticos (IDs nulos, duplicatas, notas fora do intervalo, tabelas vazias) sejam detectados antes de chegarem à camada de consumo. Sem validação, um dado corrompido poderia chegar silenciosamente ao app de recomendações.

## Como funciona

1. Recebe argumentos do job: `TABLE_NAME`, `DATABASE`, `DATABASE_RESULTS`, `S3_BUCKET_DATA_QUALITY`, `SNS_TOPIC_ARN_DQ_METRICS`, `ENVIRONMENT`, `OUTPUT_TABLE`, `YEAR` (quando aplicável)
2. Busca o ruleset DQDL correspondente à tabela em `rulesets_dq.py` (mapeado por nome de tabela)
3. Lê a tabela do Glue Catalog via Spark, aplicando filtro de partição por `year` quando disponível
4. Avalia as regras usando o motor nativo do **AWS Glue Data Quality** (DQDL)
5. Grava os resultados como Parquet na camada DQ, particionado por `source_table` e `year`
6. Se qualquer regra falhar: envia notificação via **SNS** (e-mail configurado por variável)

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `TABLE_NAME`, `DATABASE`, `DATABASE_RESULTS`, `S3_BUCKET_DATA_QUALITY`, `SNS_TOPIC_ARN_DQ_METRICS`, `ENVIRONMENT`, `OUTPUT_TABLE`, `YEAR` (opcional — apenas tabelas com partição por ano) |
| **Leitura** | Glue Catalog (tabela a ser validada na SOT ou SPEC) |
| **Escrita** | S3 DQ — resultados em Parquet particionados por `source_table` e `year` |
| **Notifica** | SNS → e-mail configurado para o job (em caso de falha) |

## Regras DQDL por tabela (`src/rulesets_dq.py`)

> **DQDL (Data Quality Definition Language)** é a linguagem nativa do AWS Glue para escrever regras de qualidade. A sintaxe é declarativa: você descreve *o que* deve ser verdade nos dados (ex: "id não pode ser nulo"), e o motor do Glue avalia e retorna Pass/Fail para cada regra.

As regras são definidas em DQDL (Data Quality Definition Language), linguagem nativa do AWS Glue. Cada tabela tem seu ruleset mapeado por nome. Exemplos:

```
# Tabela discover (filmes/séries populares)
Rules = [
  IsComplete "id",               # ID nunca pode ser nulo
  IsUnique "id",                 # Sem duplicatas por ID
  ColumnValues "vote_average" >= 0,             # Nota válida (between é exclusivo no DQDL)
  ColumnValues "vote_average" <= 10,
  ColumnValues "popularity" >= 0,               # Popularidade não pode ser negativa
  RowCount > 0                   # Tabela não pode estar vazia
]

# Tabela configuration (países/idiomas)
Rules = [
  IsComplete "iso_3166_1",       # Código ISO obrigatório
  IsComplete "native_name",
  IsComplete "english_name",
  IsComplete "name_pt",          # Tradução pt-BR obrigatória
  IsUnique "iso_3166_1",
  RowCount > 0
]

# Tabela watch_providers (provedores de streaming)
Rules = [
  IsComplete "id",
  IsComplete "provider_id",
  IsComplete "provider_name",
  IsComplete "provider_type",
  Uniqueness "id" "provider_id" "provider_type" = 1,
  ColumnValues "provider_type" in ["flatrate", "rent", "buy"],  # Enum de tipos válidos
  RowCount > 0
]
```

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job |
| `get_ruleset(table_name, environment)` | Retorna o DQDL ruleset correspondente ao nome da tabela |
| `read_table_from_catalog(glue_context, database, table_name, year)` | Lê tabela do Catalog com pushdown de partição por ano |
| `evaluate_data_quality(glue_context, dynamic_frame, ruleset, table_name, database, year)` | Executa avaliação das regras via motor Glue DQ e retorna DataFrame com resultados e colunas de contexto |
| `write_results_to_s3(df, s3_bucket_data_quality, table_name, database, output_table, year)` | Salva resultados como Parquet na camada DQ |
| `notify_failed_outcomes(df, table_name, sns_topic_arn, environment, year)` | Envia e-mail via SNS se alguma regra falhou |

## Tecnologias

- **PySpark** + **awsglue** — leitura de DynamicFrames e execução do motor DQ
- **AWS Glue Data Quality** — avaliação nativa de regras DQDL
- **awswrangler** — escrita de resultados como Parquet
- **boto3** — envio de notificações via SNS
