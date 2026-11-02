# glue_data_quality — Validador de Qualidade de Dados

## O que é

O Glue Data Quality é um job transversal do pipeline: é acionado pelo Glue ETL, pelo Glue Details e pelo Glue AGG após cada tabela ser gravada nas camadas SOT e SPEC (para entender essas camadas, veja a seção "Camadas de dados" no README). Ele avalia regras de qualidade de dados usando **DQDL** (Data Quality Definition Language — linguagem específica do AWS Glue para definir regras como "a coluna id nunca pode ser nula") contra as tabelas processadas, salva os resultados na camada **DQ** e envia notificações por e-mail via **SNS** (Simple Notification Service — serviço de notificações da AWS) caso alguma regra falhe.

## Por que existe

Garante que dados problemáticos (IDs nulos, duplicatas, notas fora do intervalo, tabelas vazias) sejam detectados antes de chegarem à camada de consumo. Sem validação, um dado corrompido poderia chegar silenciosamente ao app de recomendações.

## Como funciona

1. Recebe argumentos do job: `TABLE_NAME` (uma tabela ou uma lista separada por vírgula — ver "Múltiplas tabelas por job run" abaixo), `DATABASE`, `DATABASE_RESULTS`, `S3_BUCKET_DATA_QUALITY`, `SNS_TOPIC_ARN_DQ_METRICS`, `ENVIRONMENT`, `OUTPUT_TABLE`, `YEAR` (quando aplicável)
2. Para cada tabela de `TABLE_NAME`, busca o ruleset DQDL correspondente em `rulesets_dq.py` (mapeado por nome de tabela)
3. Para cada ano em `YEAR` (ver "Múltiplos anos por job run" abaixo): lê a tabela do Glue Catalog via Spark, aplicando filtro de partição por `year`; se a partição não tiver dados (ver "Partição inexistente ou vazia" abaixo), pula esse ano; senão, avalia as regras usando o motor nativo do **AWS Glue Data Quality** (DQDL); grava os resultados como Parquet na camada DQ, particionado por `source_table` e `year`; se qualquer regra falhar, envia notificação via **SNS** (e-mail configurado por variável)

### Múltiplos anos por job run

`YEAR` pode ser um único valor (`"2025"`, ciclo normal), ausente (tabelas sem partição por ano) ou uma **lista separada por vírgula** (`"2020,2021,2023"`) — usado pelo modo changes do `glue_details`, que agrupa todos os anos afetados por uma janela de mudanças da Changes API num único disparo de job, em vez de um disparo por ano. `main()` faz `YEAR.split(",")` e itera a leitura/avaliação/escrita/notificação uma vez por ano, dentro do mesmo `SparkContext` — preserva a mesma granularidade de resultado por partição (cada ano ainda gera sua própria avaliação e escrita), só paga o overhead fixo de startup do Spark uma vez em vez de N vezes.

### Múltiplas tabelas por job run

`TABLE_NAME` pode ser uma única tabela (`"tb_tmdb_genre_movie_prod"`, o que ETL, AGG e os scripts de backfill enviam) ou uma **lista separada por vírgula** (`"tb_tmdb_details_movie_prod,tb_tmdb_watch_providers_movie_prod"`) — usado pelo `glue_details` no ciclo normal (discover semanal, rotation, mensal e ano futuro), que grava `details` e `watch_providers` do mesmo ano e dispara **um** run em vez de dois. As tabelas da lista precisam estar no mesmo `DATABASE` e compartilham a mesma lista de `YEAR`. `main()` faz `TABLE_NAME.split(",")` (ignorando espaços e itens vazios) e, dentro do mesmo `SparkContext`, avalia cada tabela em sequência (`_evaluate_table`: ruleset → anos → leitura → avaliação → escrita → notificação) — os resultados continuam particionados por `source_table` e `year`, e a notificação continua por tabela, então nada muda para quem consome a camada DQ; só o overhead fixo de startup do Spark é pago uma vez em vez de uma por tabela.

Cada tabela é isolada das demais: se a avaliação de uma falha (ex.: tabela sem regras em `rulesets_dq.py`, erro do motor de DQ), `main()` registra o erro (`logger.exception`), segue para a próxima e só no final levanta `RuntimeError` listando as tabelas que falharam — o job termina em `FAILED` (os alarmes do Glue continuam valendo), mas uma tabela ruim não deixa a outra sem validação. Uma lista de `TABLE_NAME` vazia (só vírgulas/espaços) levanta `ValueError`.

O modo changes do `glue_details` **não** usa a lista de tabelas: ele já itera dezenas de anos por tabela, e juntar as duas dobraria a duração do run contra o timeout de 30 min do job. Só vale agregar depois de medir essa duração em prod.

### Partição inexistente ou vazia

No modo changes, o `year` de cada tabela vem do dado real gravado por `glue_details` (release_date/first_air_date via API, sem nenhum floor de ano — ver `glue_details.md`, seção "Modo changes"), não de um argumento fixo como no ciclo normal. Isso significa que o job pode ser acionado para um `year` cuja partição nunca foi escrita numa tabela específica — ex.: `watch_providers` não grava nada quando nenhum id do grupo tem provedores de streaming no Brasil, mas esse `year` ainda entra na lista de anos afetados. Quando isso acontece, `read_table_from_catalog` devolve um `DynamicFrame` vazio (sem partição correspondente no catálogo), e converter esse frame vazio para Spark DataFrame (`.toDF()`) resultaria num schema sem colunas — qualquer filtro subsequente (`col("year")`) quebraria com `UNRESOLVED_COLUMN`. Por isso, antes de avaliar, `main()` chama `has_data(dynamic_frame)`: se vazio, loga um `warning` e pula esse ano (`continue`) — sem gravar resultado nem notificar, mas sem derrubar o job nem os demais anos do mesmo run multi-year.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `TABLE_NAME` (uma tabela ou lista separada por vírgula), `DATABASE`, `DATABASE_RESULTS`, `S3_BUCKET_DATA_QUALITY`, `SNS_TOPIC_ARN_DQ_METRICS`, `ENVIRONMENT`, `OUTPUT_TABLE`, `YEAR` (opcional — apenas tabelas com partição por ano; pode ser um único ano ou uma lista separada por vírgula) |
| **Leitura** | Glue Catalog (tabela a ser validada na SOT ou SPEC) |
| **Escrita** | S3 DQ — resultados em Parquet particionados por `source_table` e `year` |
| **Notifica** | SNS → e-mail configurado para o job (em caso de falha) |

## Regras DQDL por tabela (`src/rulesets_dq.py`)

> **DQDL (Data Quality Definition Language)** é a linguagem nativa do AWS Glue para escrever regras de qualidade. A sintaxe é declarativa: você descreve *o que* deve ser verdade nos dados (ex: "id não pode ser nulo"), e o motor do Glue avalia e retorna Pass/Fail para cada regra.

As regras são definidas em DQDL (Data Quality Definition Language), linguagem nativa do AWS Glue. Cada tabela tem seu ruleset mapeado por nome — ao todo, 14 tabelas têm regras cadastradas (incluindo `now_playing_movie` e `discover_unified`, a tabela unificada gerada pelo Glue AGG). Exemplos:

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
| `has_data(dynamic_frame)` | Verifica se o `DynamicFrame` tem ao menos um registro (`count() > 0`) — usado para pular graciosamente um `year` cuja partição não existe/está vazia, em vez de quebrar em `UNRESOLVED_COLUMN` (ver "Partição inexistente ou vazia" acima) |
| `evaluate_data_quality(glue_context, dynamic_frame, ruleset, table_name, database, year)` | Executa avaliação das regras via motor Glue DQ e retorna DataFrame com resultados e colunas de contexto |
| `write_results_to_s3(df, s3_bucket_data_quality, source_table_name, database, output_table, year)` | Salva resultados como Parquet na camada DQ |
| `notify_failed_outcomes(df, table_name, sns_topic_arn, environment, year)` | Envia e-mail via SNS se alguma regra falhou |

## Tecnologias

- **PySpark** + **awsglue** — leitura de DynamicFrames e execução do motor DQ
- **AWS Glue Data Quality** — avaliação nativa de regras DQDL
- **awswrangler** — escrita de resultados como Parquet
- **boto3** — envio de notificações via SNS
