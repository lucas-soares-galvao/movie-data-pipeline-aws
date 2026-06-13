# glue_etl — Transformador (JSON → Parquet)

## O que é

O Glue ETL é o segundo estágio do pipeline. Recebe dados brutos em JSON salvos pela Lambda no S3 SOR, os transforma para o formato Parquet estruturado e os grava na camada SOT (Source of Truth). Também registra as tabelas no Glue Catalog para que sejam consultáveis via Athena. Ao final, aciona o Glue Data Quality e, para tabelas `discover`, aciona o Glue Details.

## Por que existe

JSON bruto é flexível mas ineficiente para análise. Parquet é colunar, comprimido e nativo para consultas SQL via Athena. Este job faz essa conversão garantindo schema consistente e particionamento correto por ano.

## Conceitos-chave

- **SOR (System of Record)** — camada de dados brutos. Contém os JSONs exatamente como vieram da API TMDB, sem nenhuma modificação.
- **SOT (Source of Truth)** — camada refinada. Dados convertidos para Parquet, com schema fixo e particionamento, prontos para consulta via SQL.
- **Parquet** — formato de arquivo colunar e comprimido, muito mais eficiente que JSON para análise de dados: ocupa menos espaço em disco e é mais rápido para leitura por ferramentas como Athena e Spark.
- **Glue Catalog** — catálogo centralizado de metadados da AWS. Registra onde cada tabela está no S3 e qual é o seu schema, permitindo consultá-la com SQL via Athena sem precisar especificar o caminho manualmente.

## Como funciona

O job recebe argumentos dinâmicos injetados pela Lambda no momento do disparo (`start_job_run`). O comportamento varia conforme `TABLE_TYPE`:

| `TABLE_TYPE` | Particionamento | Modo de escrita | Aciona Details? |
|---|---|---|---|
| `discover` | Por `year` | `overwrite_partitions` (preserva outros anos) | Sim |
| `genre` | Sem partição | `overwrite` (substitui tudo) | Não |
| `configuration` | Sem partição | `overwrite` | Não |
| `watch_providers_ref` | Sem partição | `overwrite` | Não |

**Fluxo para `discover`:**
1. Lê os argumentos do Glue (`get_parameters_glue`)
2. Lê o JSON do S3 SOR para o ano especificado (`read_from_sor`)
3. Escreve Parquet na SOT particionado por `year`, modo `overwrite_partitions` (`write_parquet_to_sot`)
4. Aciona Glue Data Quality para a tabela processada (`trigger_data_quality`)
5. Aciona Glue Details para enriquecimento (`trigger_details`)

**Fluxo para tabelas estáticas (genre, configuration, watch_providers_ref):**
1–4 iguais ao discover, sem step 5.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos do Glue job: `MEDIA_TYPE`, `TABLE_TYPE`, `TABLE_NAME`, `DATABASE`, `YEAR` (apenas discover), `END_YEAR`, nomes dos buckets e jobs |
| **Leitura** | S3 SOR — JSON bruto por tipo de tabela e ano |
| **Escrita** | S3 SOT — Parquet particionado (ou não) + registro no Glue Catalog |
| **Aciona** | Glue Data Quality (sempre) + Glue Details (apenas para `TABLE_TYPE=discover`) |

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job |
| `read_from_sor(bucket, media_type, table_type, year)` | Lê JSON/Parquet da camada SOR |
| `write_parquet_to_sot(df, bucket, table_name, database, partition_cols, mode)` | Escreve Parquet e registra no Glue Catalog via AWS Wrangler |
| `normalize_watch_providers(df)` | Padroniza nomes de plataformas de streaming (ex: "Netflix" ao invés de variantes) |
| `trigger_data_quality(dq_job_name, table_name, database, year)` | Aciona o job de qualidade de dados |
| `trigger_details(details_job_name, media_type, year, end_year, database)` | Aciona o job de enriquecimento de detalhes |

## Tecnologias

- **awswrangler** — leitura/escrita de Parquet no S3 e registro no Glue Catalog
- **pandas** — manipulação de DataFrames
- **boto3** — acionamento de outros jobs Glue
- **Glue runtime** — execução do job no ambiente AWS Glue
