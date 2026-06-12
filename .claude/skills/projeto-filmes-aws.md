# Skill: Contexto do Projeto de Engenharia de Dados com AWS

Você está trabalhando no projeto **proj-eng-dados-filmes-aws**, um pipeline de engenharia de dados serverless na AWS que coleta, transforma, avalia e unifica dados de filmes e séries da API do TMDB.

---

## Arquitetura do Pipeline

```
EventBridge (schedule)
       │
       ▼
  Lambda (app/lambda_api/)
  ├── Busca dados da API TMDB (discover, genres, configuration)
  ├── Salva JSON bruto no S3 SOR
  └── Dispara Glue ETL job
       │
       ▼
  Glue ETL (app/glue_etl/)
  ├── Lê JSON do S3 SOR
  ├── Transforma para Parquet (via awswrangler)
  ├── Salva no S3 SOT e registra no Glue Catalog
  └── Dispara Glue Data Quality job
       │
       ▼
  Glue Data Quality (app/glue_data_quality/)
  ├── Lê tabela do Glue Catalog (com pushdown predicate)
  ├── Avalia rulesets DQDL definidos em rulesets_dq.py
  ├── Salva resultado em Parquet no S3 (bucket DQ)
  └── Registra partição na tabela tb_data_quality_tmdb no Glue Catalog
       │
       ▼
  Glue Details (app/glue_details/)
  ├── Lê tabelas discover do S3 SOT
  ├── Busca detalhes complementares na API TMDB (runtime, temporadas, streaming BR)
  ├── Salva em S3 SOT (tb_details_movie_tmdb / tb_details_tv_tmdb)
  └── Dispara Glue AGG job
       │
       ▼
  Glue AGG (app/glue_agg/)
  ├── Une filmes e séries com seus detalhes
  ├── Traduz title e overview do inglês para o português (deep-translator)
  ├── Salva tabela unificada em S3 SPEC (tb_discover_unified_tmdb)
  └── Registra tabela no Glue Catalog
       │
       ▼
  FilmBot — Lightsail (app/lightsail_ia/)
  ├── Usuário digita pedido em linguagem natural
  ├── GPT-4o extrai filtros via Function Calling (etapa 1)
  ├── Consulta tb_discover_unified_tmdb no Athena (etapa 2)
  └── GPT-4o formata recomendações com poster, sinopse, streaming (etapa 3)
```

---

## Camadas de Dados (Buckets S3)

| Camada | Descrição | Formato |
|--------|-----------|---------|
| **SOR** (System of Record) | Dados brutos da API TMDB | JSON |
| **SOT** (System of Truth) | Dados transformados por tabela | Parquet particionado |
| **SPEC** (Specialized) | Dados unificados filmes + séries | Parquet |
| **DQ** | Resultados de data quality | Parquet particionado por `source_table` |

---

## Estrutura de Código

```
app/
├── lambda_api/
│   ├── main.py              # handler Lambda: extrai, salva SOR, dispara Glue ETL
│   └── src/utils.py         # fetch TMDB, save S3, trigger Glue ETL
├── glue_etl/
│   ├── main.py              # resolve args Glue e chama run_etl()
│   └── src/utils.py         # process_tmdb(), call_glue_data_quality(), run_etl()
├── glue_data_quality/
│   ├── main.py              # orquestra DQ: lê catálogo, avalia, salva, registra
│   └── src/
│       ├── utils.py         # parse_args, build_ruleset, run_data_quality, write_results, register_partition
│       └── rulesets_dq.py   # dict de rulesets DQDL por nome de tabela
├── glue_details/
│   ├── main.py              # resolve args Glue e chama run_details()
│   └── src/utils.py         # busca detalhes TMDB, streaming providers, salva SOT
├── glue_agg/
│   ├── main.py              # resolve args Glue e chama run_agg()
│   └── src/utils.py         # une filmes+séries, traduz, salva SPEC
└── lightsail_ia/
    ├── agent.py             # recomendar() + buscar_titulos_spec() (3 etapas: LLM → Athena → LLM)
    └── app.py               # interface Streamlit (FilmBot)
test/
├── lambda_api/
├── glue_etl/
├── glue_data_quality/
├── glue_details/
├── glue_agg/
└── lightsail/
```

---

## Tabelas no Glue Catalog

### Banco SOT (ex: `db_tmdb_sot`)
| Tabela | Conteúdo | Partições |
|--------|----------|-----------|
| `tb_discover_movie_tmdb` | Filmes descobertos | `year`, `month` |
| `tb_discover_tv_tmdb` | Séries descobertas | `year`, `month` |
| `tb_genre_movie_tmdb` | Gêneros de filmes | — |
| `tb_genre_tv_tmdb` | Gêneros de séries | — |
| `tb_configuration_languages_tmdb` | Idiomas | — |
| `tb_configuration_countries_tmdb` | Países | — |
| `tb_data_quality_tmdb` | Resultados de DQ | `source_table` |
| `tb_details_movie_tmdb` | Detalhes de filmes (runtime, streaming) | `year` |
| `tb_details_tv_tmdb` | Detalhes de séries (temporadas, episódios, streaming) | `year` |

### Banco SPEC (ex: `db_tmdb_spec`)
| Tabela | Conteúdo |
|--------|----------|
| `tb_discover_unified_tmdb` | União de filmes + séries com detalhes e tradução PT |

---

## Paths S3 (convenções)

**SOR:**
- `tmdb/discover/{media_type}/year={year}/month={month}/{media_type}_{year}_{month}.json`
- `tmdb/genre/{media_type}/genres_{media_type}.json`
- `tmdb/configuration/{type}/configuration_{type}.json`

**SOT:**
- `tmdb/{table_name}/` (dataset Parquet particionado)

**DQ:**
- `tmdb/tb_data_quality_tmdb/source_table={table_name}/`

---

## Variáveis de Ambiente (Lambda)

| Variável | Descrição |
|----------|-----------|
| `TMDB_SECRET_ARN` | ARN do Secret Manager com a chave TMDB |
| `GLUE_ETL_JOB_NAME` | Nome do Glue job de ETL |
| `S3_BUCKET_SOR` | Nome do bucket SOR |

---

## Argumentos dos Glue Jobs

### Glue ETL
```
--S3_BUCKET_SOR, --S3_BUCKET_SOT, --MEDIA_TYPE, --DATABASE
--DISCOVER_TABLE, --GENRE_TABLE, --CONFIGURATION_TABLE
--CONFIGURATION, --PARTITION_COLUMNS, --GLUE_DATA_QUALITY_JOB_NAME
--YEAR (opcional), --TABLE_SCOPE (opcional: all | discover | static)
```

### Glue Data Quality
```
--DATABASE, --TABLE, --S3_BUCKET_DATA_QUALITY
--PARTITION_VALUES (opcional, ex: "year=2024")
```

---

## Fluxo do Evento Lambda

O evento JSON recebido pela Lambda deve conter:
```json
{
  "type": "movie",            // ou "tv"
  "database": "db_tmdb_sot",
  "table_discover_movie": "tb_discover_movie_tmdb",
  "table_genre_movie": "tb_genre_movie_tmdb",
  "table_configuration_languages": "tb_configuration_languages_tmdb"
}
```
O EventBridge dispara a Lambda automaticamente no horário configurado.

---

## Segurança e Observabilidade

- **IAM**: Roles e policies com privilégio mínimo por componente (Lambda, Glue ETL, Glue DQ)
- **Secrets Manager**: Chave da API TMDB armazenada como secret
- **CloudWatch Alarms**: Alarmes configurados para cada etapa do pipeline, com notificações por e-mail via SNS
- **Glue DQ CloudWatch Metrics**: `enableDataQualityCloudWatchMetrics: True` no job de DQ

---

## Rulesets de Data Quality (DQDL)

Definidos em `app/glue_data_quality/src/rulesets_dq.py`. Cada tabela tem regras como:
- `IsComplete` / `IsUnique` para colunas-chave
- `ColumnValues "vote_average" between 0 and 10`
- `RowCount > 0` (regra padrão para qualquer tabela sem ruleset definido)

---

## Convenções de Desenvolvimento

- Testes em `test/` espelhando a estrutura de `app/`
- `conftest.py` por módulo para fixtures compartilhadas
- `awswrangler` para I/O com S3 e Glue Catalog no ETL
- `boto3` diretamente para chamadas ao Glue, Secrets Manager e S3 na Lambda
- Particionamento temporal: `year` e `month` extraídos das colunas `release_date` (movie) e `first_air_date` (tv)
