# Skill: Contexto do Projeto de Engenharia de Dados com AWS

Você está trabalhando no projeto **proj-eng-dados-filmes-aws**, um pipeline de engenharia de dados serverless na AWS que coleta, transforma, avalia e unifica dados de filmes e séries da API do TMDB.

---

## Arquitetura do Pipeline

```
EventBridge (schedule)
       │
       ▼
  Lambda (app/lambda_api/)
  ├── Busca dados da API TMDB (discover, genres, configuration, watch_providers_ref, now_playing)
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
  └── Registra partição na tabela tb_tmdb_data_quality_{env} no Glue Catalog
       │
       ▼
  Glue Details (app/glue_details/)
  ├── Lê tabelas discover do S3 SOT
  ├── Busca detalhes complementares na API TMDB (runtime, temporadas, episódios)
  ├── Busca streaming providers do Brasil por título (tb_tmdb_watch_providers_{media_type}_{env})
  ├── Salva em S3 SOT (tb_tmdb_details_{media_type}_{env} + tb_tmdb_watch_providers_{media_type}_{env})
  ├── Lógica delta: só busca IDs que ainda não existem na camada details
  ├── Repara duplicatas nas partições (discover, details, watch_providers)
  └── Dispara Glue AGG job apenas quando year == end_year (último ano do ciclo)
       │
       ▼
  Glue AGG (app/glue_agg/)
  ├── Une filmes e séries via Athena SQL com CTEs e DENSE_RANK
  ├── Joins com gêneros, detalhes, streaming providers e now_playing
  ├── Deduplicação final por (id, media_type)
  ├── Salva tabela unificada em S3 SPEC (tb_tmdb_discover_unified_{env})
  ├── Registra tabela no Glue Catalog
  └── Dispara Glue Data Quality final
       │
       ▼
  FilmBot — Lightsail (app/lightsail_ia/)
  ├── Usuário digita pedido em linguagem natural
  ├── LLM (configurável via LLM_MODEL) extrai filtros via Function Calling (etapa 1)
  ├── Consulta tb_tmdb_discover_unified_{env} no Athena (etapa 2)
  └── Formatação determinística em Python com poster, sinopse, streaming (etapa 2.5)
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
│   ├── main.py              # resolve args Glue e chama main()
│   └── src/utils.py         # get_parameters_glue(), read_from_sor(), write_parquet_to_sot(), derive_canonical_name()
├── glue_data_quality/
│   ├── main.py              # orquestra DQ: lê catálogo, avalia, salva, notifica
│   └── src/
│       ├── utils.py         # get_parameters_glue, get_ruleset, read_table_from_catalog, evaluate_data_quality, write_results_to_s3, notify_failed_outcomes
│       └── rulesets_dq.py   # dict de rulesets DQDL por nome de tabela
├── glue_details/
│   ├── main.py              # resolve args Glue e chama main()
│   └── src/utils.py         # busca detalhes TMDB, traduz sinopses EN→PT, streaming providers, salva SOT
├── glue_agg/
│   ├── main.py              # resolve args Glue e chama main()
│   └── src/utils.py         # get_parameters_glue(), run_athena_query(), write_parquet_to_spec()
├── lightsail_ia/
│   ├── agent.py             # recomendar() + buscar_titulos_spec() (2 etapas: LLM → Athena → formatação Python)
│   └── app.py               # interface Streamlit (FilmBot)
├── lambda_lightsail_scheduler/
│   └── main.py               # handler Lambda: liga/desliga instância Lightsail
└── shared_src/
    └── shared_utils/
        ├── api_client.py       # API client genérico com retry/backoff e Secrets Manager (compartilhado)
        ├── glue_helpers.py     # utilitários compartilhados de jobs Glue (compartilhado)
        ├── traducao.py         # tradução inglês → português: Google Translate + fallback AWS Translate (compartilhado)
        └── triggers.py        # disparo genérico de Glue jobs (compartilhado)
test/
├── lambda_api/
├── glue_etl/
├── glue_data_quality/
├── glue_details/
├── glue_agg/
├── lightsail_ia/
├── lambda_lightsail_scheduler/
└── shared_src/
```

---

## Tabelas no Glue Catalog

### Banco Movie (`db_tmdb_movie_{env}`)
| Tabela | Conteúdo | Partições |
|--------|----------|-----------|
| `tb_tmdb_discover_movie_{env}` | Filmes descobertos | `year` |
| `tb_tmdb_genre_movie_{env}` | Gêneros de filmes | — |
| `tb_tmdb_configuration_languages_{env}` | Idiomas (com `name_pt` traduzido via Google Translate) | — |
| `tb_tmdb_details_movie_{env}` | Detalhes de filmes (runtime, streaming) | `year` |
| `tb_tmdb_watch_providers_movie_{env}` | Plataformas de streaming (filmes) | `year` |
| `tb_tmdb_watch_providers_ref_movie_{env}` | Referência de provedores (filmes) | — |
| `tb_tmdb_now_playing_movie_{env}` | Filmes em cartaz nos cinemas | — |

### Banco TV (`db_tmdb_tv_{env}`)
| Tabela | Conteúdo | Partições |
|--------|----------|-----------|
| `tb_tmdb_discover_tv_{env}` | Séries descobertas | `year` |
| `tb_tmdb_genre_tv_{env}` | Gêneros de séries | — |
| `tb_tmdb_configuration_countries_{env}` | Países (com `name_pt` traduzido via Google Translate) | — |
| `tb_tmdb_details_tv_{env}` | Detalhes de séries (temporadas, episódios, streaming) | `year` |
| `tb_tmdb_watch_providers_tv_{env}` | Plataformas de streaming (séries) | `year` |
| `tb_tmdb_watch_providers_ref_tv_{env}` | Referência de provedores (séries) | — |

### Banco Unified (`db_tmdb_unified_{env}`)
| Tabela | Conteúdo | Partições |
|--------|----------|-----------|
| `tb_tmdb_data_quality_{env}` | Resultados de DQ | `source_table`, `year` |
| `tb_tmdb_discover_unified_{env}` | União de filmes + séries (SPEC, registrada em runtime pelo AGG). Inclui colunas `in_theaters`, `theater_start_date`, `theater_end_date` para filmes em cartaz | `media_type`, `year` |

---

## Paths S3 (convenções)

**SOR:**
- `tmdb/discover/{media_type}/year={year}/month={month}/{media_type}_{year}_{month}.json`
- `tmdb/genre/{media_type}/genres_{media_type}.json`
- `tmdb/configuration/{type}/configuration_{type}.json`

**SOT:**
- `tmdb/{table_name}/` (dataset Parquet particionado)

**DQ:**
- `tmdb/tb_tmdb_data_quality_{env}/source_table={table_name}/`

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
--TABLE_NAME, --TABLE_TYPE, --GLUE_DATA_QUALITY_JOB_NAME, --GLUE_DETAILS_JOB_NAME
--YEAR (opcional), --END_YEAR (opcional — apenas para runs de discover)
```

### Glue Data Quality
```
--TABLE_NAME, --DATABASE, --DATABASE_RESULTS, --S3_BUCKET_DATA_QUALITY
--SNS_TOPIC_ARN_DQ_METRICS, --ENVIRONMENT, --OUTPUT_TABLE
--YEAR (opcional — apenas tabelas com partição por ano)
```

### Glue Details
```
--S3_BUCKET_SOT, --S3_BUCKET_TEMP, --DATABASE
--TABLE_DISCOVER_MOVIE, --TABLE_DISCOVER_TV
--TABLE_DETAILS_MOVIE, --TABLE_DETAILS_TV
--TABLE_WATCH_PROVIDERS_MOVIE, --TABLE_WATCH_PROVIDERS_TV
--TMDB_SECRET_ARN, --GLUE_AGG_JOB_NAME, --GLUE_DATA_QUALITY_JOB_NAME
--MEDIA_TYPE, --YEAR, --END_YEAR
```

### Glue AGG
```
--S3_BUCKET_SPEC, --S3_PREFIX_SPEC, --S3_BUCKET_TEMP
--DB_MOVIE, --DB_TV, --DB_UNIFIED
--TABLE_NAME, --GLUE_DATA_QUALITY_JOB_NAME, --ENVIRONMENT
```

---

## Fluxo do Evento Lambda

O evento JSON recebido pela Lambda deve conter (exemplo para filmes, semanal):
```json
{
  "type": "movie",
  "only_weekly_tables": true,
  "database": "db_tmdb_movie_{env}",
  "database_unified": "db_tmdb_unified_{env}",
  "table_discover_movie": "tb_tmdb_discover_movie_{env}",
  "table_genre_movie": "tb_tmdb_genre_movie_{env}",
  "table_configuration_languages": "tb_tmdb_configuration_languages_{env}",
  "table_watch_providers_ref_movie": "tb_tmdb_watch_providers_ref_movie_{env}",
  "table_now_playing_movie": "tb_tmdb_now_playing_movie_{env}"
}
```
O EventBridge dispara a Lambda automaticamente no horário configurado. Para séries (`type: "tv"`), as chaves mudam para `table_discover_tv`, `table_genre_tv`, `table_configuration_countries`, `table_watch_providers_ref_tv`. Os flags opcionais de controle são: `only_weekly_tables` (semanal), `only_annual_tables` (backfill anual), `only_monthly_tables` (mensal), `skip_weekly` (apenas referências).

---

## Segurança e Observabilidade

- **IAM**: Roles e policies com privilégio mínimo por componente (Lambda, Glue ETL, Glue DQ) e para a role do GitHub Actions (`iam_cicd.tf` — 6 policies scoped a `tmdb-*` e `lsg-sa-east-1-bucket-*`); `glue_details_role`, `glue_etl_role` e a role de backfill também têm `translate:TranslateText` (fallback de tradução via AWS Translate — `Resource = "*"`, AWS não restringe esse action por recurso)
- **Secrets Manager**: secret unificado (`filmbot_secret_arn`) com `tmdb_api_key`, `llm_api_key` (LLM do FilmBot) e `filmbot_password`; `glue_details` recebe esse ARN como `TMDB_SECRET_ARN`
- **CloudWatch Alarms**: Alarmes configurados para cada etapa do pipeline, com notificações por e-mail via SNS
- **Glue DQ CloudWatch Metrics**: `enableDataQualityCloudWatchMetrics: True` no job de DQ

---

## Rulesets de Data Quality (DQDL)

Definidos em `app/glue_data_quality/src/rulesets_dq.py`. As 14 tabelas têm regras organizadas por dimensão:
- **Completude**: `IsComplete` para colunas-chave (`id`, `title`, `name_pt`, `canonical_name`, etc.)
- **Unicidade**: `IsUnique` ou `Uniqueness` (composta) para chaves primárias
- **Validade**: `ColumnValues` para ranges (`vote_average >= 0 AND <= 10`, `popularity >= 0`, `budget >= 0`, `revenue >= 0`, `runtime >= 0`) e enums (`media_type in ["movie", "tv"]`, `provider_type in ["flatrate", "rent", "buy"]`)
- **Integridade**: `RowCount > 0` em todas as tabelas

---

## Convenções de Desenvolvimento

- Testes em `test/` espelhando a estrutura de `app/`
- `conftest.py` por módulo para fixtures compartilhadas
- `awswrangler` para I/O com S3 e Glue Catalog no ETL
- `boto3` diretamente para chamadas ao Glue, Secrets Manager e S3 na Lambda
- Particionamento temporal: `year` e `month` extraídos das colunas `release_date` (movie) e `first_air_date` (tv)
