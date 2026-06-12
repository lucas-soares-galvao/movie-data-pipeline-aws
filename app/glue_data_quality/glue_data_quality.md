# glue_data_quality — Validador de Qualidade de Dados

## O que é

O Glue Data Quality é um job transversal do pipeline: é acionado pelo Glue ETL e pelo Glue Details após cada tabela ser gravada na SOT. Ele avalia regras de qualidade de dados (DQDL) contra as tabelas processadas, salva os resultados na camada DQ e envia notificações por e-mail via SNS caso alguma regra falhe.

## Por que existe

Garante que dados problemáticos (IDs nulos, duplicatas, notas fora do intervalo, tabelas vazias) sejam detectados antes de chegarem à camada de consumo. Sem validação, um dado corrompido poderia chegar silenciosamente ao app de recomendações.

## Como funciona

1. Recebe argumentos do job: `TABLE_NAME`, `DATABASE`, `YEAR` (quando aplicável), `ENVIRONMENT`
2. Busca o ruleset DQDL correspondente à tabela em `rulesets_dq.py` (mapeado por nome de tabela)
3. Lê a tabela do Glue Catalog via Spark, aplicando filtro de partição por `year` quando disponível
4. Avalia as regras usando o motor nativo do **AWS Glue Data Quality** (DQDL)
5. Grava os resultados como Parquet na camada DQ, particionado por `source_table` e `year`
6. Se qualquer regra falhar: envia notificação via **SNS** (e-mail configurado por variável)

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `TABLE_NAME`, `DATABASE`, `YEAR`, `ENVIRONMENT`, nomes dos buckets e SNS topic |
| **Leitura** | Glue Catalog (tabela a ser validada na SOT) |
| **Escrita** | S3 DQ — resultados em Parquet particionados por `source_table` e `year` |
| **Notifica** | SNS → e-mail configurado para o job (em caso de falha) |

## Regras DQDL por tabela (`src/rulesets_dq.py`)

As regras são definidas em DQDL (Data Quality Definition Language), linguagem nativa do AWS Glue. Cada tabela tem seu ruleset mapeado por nome. Exemplos:

```
# Tabela discover (filmes/séries populares)
Rules = [
  IsComplete "id",               # ID nunca pode ser nulo
  IsUnique "id",                 # Sem duplicatas por ID
  RowCount > 0,                  # Tabela não pode estar vazia
  ColumnValues "vote_average" between 0 and 10  # Nota válida
]

# Tabela genre
Rules = [
  IsComplete "id",
  IsComplete "name",
  IsUnique "id"
]
```

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job |
| `get_ruleset(table_name)` | Retorna o DQDL ruleset correspondente ao nome da tabela |
| `read_table_from_catalog(glue_context, database, table_name, year)` | Lê tabela do Catalog com pushdown de partição por ano |
| `evaluate_data_quality(glue_context, dynamic_frame, ruleset)` | Executa avaliação das regras via motor Glue DQ |
| `write_results_to_s3(results_df, bucket, table_name, year)` | Salva resultados como Parquet na camada DQ |
| `notify_failed_outcomes(sns_topic_arn, results_df, table_name)` | Envia e-mail via SNS se alguma regra falhou |

## Tecnologias

- **PySpark** + **awsglue** — leitura de DynamicFrames e execução do motor DQ
- **AWS Glue Data Quality** — avaliação nativa de regras DQDL
- **awswrangler** — escrita de resultados como Parquet
- **boto3** — envio de notificações via SNS
