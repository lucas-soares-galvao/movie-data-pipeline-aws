# Testes — glue_agg

## O que é testado

Testa a função `main()` em `app/glue_agg/main.py` e as funções utilitárias em `app/glue_agg/src/utils.py`. O ponto central é garantir que as duas etapas principais do pipeline (query Athena → escrita na SPEC) e o acionamento do Data Quality ocorrem na **ordem correta** e com os argumentos certos. Todas as dependências externas (Athena, S3) são substituídas por **mocks** — objetos falsos que simulam o comportamento esperado sem fazer chamadas reais, mantendo os testes rápidos, gratuitos e isolados.

## Estrutura

```
test/glue_agg/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes da função main()
└── test_utils.py             # Testes das funções utilitárias
```

## Fixtures (`conftest.py`)

| Fixture | Tipo | Descrição |
|---|---|---|
| `_BASE_ARGS` (constante) | `dict` | Argumentos simulados do Glue job (databases, buckets, table name) |
| `_DF_MOCK` (constante) | `pd.DataFrame` | DataFrame de 2 linhas simulando o resultado da query Athena |

## Casos de teste — `test_main.py`

### `TestMain`

| Teste | O que verifica |
|---|---|
| `test_calls_run_athena_query_with_correct_args` | `run_athena_query` chamado com os 4 argumentos corretos (db_movie, db_tv, db_unified, s3_bucket_temp) |
| `test_calls_write_parquet_to_spec_with_correct_args` | `write_parquet_to_spec` chamado com df, bucket, table_name e database corretos |
| `test_write_receives_dataframe_returned_by_query` | O DataFrame passado para `write_parquet_to_spec` é exatamente o que `run_athena_query` retornou |
| `test_pipeline_runs_without_exceptions` | Execução completa não levanta nenhuma exceção |
| `test_write_called_exactly_once` | `write_parquet_to_spec` é chamado exatamente uma vez |
| `test_query_called_exactly_once` | `run_athena_query` é chamado exatamente uma vez |
| `test_dataframe_vazio_nao_escreve_mas_aciona_dq` | Quando `run_athena_query` retorna DataFrame vazio, `write_parquet_to_spec` ainda é chamado uma vez e `trigger_data_quality` também |
| `test_aciona_dq_apos_escrita_sem_year` | **Ordem garantida:** `write_parquet_to_spec` → `trigger_data_quality` (usando `call_order[]`); DQ chamado sem `year`, com `table_name` e `database` corretos |

> **Destaque:** `test_aciona_dq_apos_escrita_sem_year` usa uma lista compartilhada `call_order` nos side_effects dos mocks de `write` e `dq` para verificar a ordem de execução — garante que a escrita na SPEC ocorra *antes* de acionar a validação de qualidade.

## Casos de teste — `test_utils.py`

### `TestRunAthenaQuery`

| Teste | O que verifica |
|---|---|
| `test_passes_sql_with_image_columns_to_wrangler` | SQL passado ao wrangler contém `AS poster_url`, `AS backdrop_url` com prefixos de URL do TMDB, `overview`, `air_date`, `origin_country_name`, `language_name` e referências a `tb_discover_movie_tmdb` e `tb_discover_tv_tmdb` |
| `test_uses_expected_wrangler_execution_args` | `read_sql_query` é chamado com `database="db_unified_tmdb"`, `s3_output="s3://temp/athena/glue_agg/"` e `ctas_approach=True` |
| `test_query_contains_details_movie_join` | SQL contém `tb_details_movie_tmdb` e coluna `runtime_minutes` |
| `test_query_contains_details_tv_join` | SQL contém `tb_details_tv_tmdb` e colunas `number_of_seasons`, `number_of_episodes`, `episode_runtime_minutes` |
| `test_query_contains_watch_providers_join` | SQL contém `tb_watch_providers_movie_tmdb`, `tb_watch_providers_tv_tmdb` e coluna `streaming_providers` |
| `test_query_deduplica_watch_providers_por_ano_mais_recente` | SQL contém CTEs `movie_wp_recent` / `tv_wp_recent` com `DENSE_RANK()` e `CAST(year AS INTEGER) DESC`; garante que **não** usa `ROW_NUMBER()` (que filtraria um único provedor por título em vez de todos do ano mais recente) |
| `test_query_possui_dedup_final_spec_deduped` | SQL contém CTEs `spec_raw` e `spec_deduped` com `PARTITION BY id, media_type` e alias `rn_final` para garantir unicidade na saída |

### `TestWriteParquetToSpec`

| Teste | O que verifica |
|---|---|
| `test_constroi_caminho_s3_correto` | Argumento `path` é `"s3://{s3_bucket_spec}/{table_name}/"` |
| `test_usa_partition_cols_e_mode_corretos` | `partition_cols=["media_type", "year"]`, `mode="overwrite"` e `dataset=True` |
| `test_dataframe_vazio_nao_escreve` | `to_parquet` não é chamado quando o DataFrame está vazio |
| `test_registra_tabela_no_catalog` | `to_parquet` recebe `database` e `table` corretos para registrar no Glue Catalog |
| `test_levanta_runtime_error_quando_nenhum_arquivo_escrito` | Levanta `RuntimeError("Escrita falhou")` quando `to_parquet` retorna `{"paths": []}` (nenhum arquivo gravado) |

### `TestTriggerDataQuality`

| Teste | O que verifica |
|---|---|
| `test_inicia_job_sem_year` | `--YEAR` ausente nos argumentos; `--TABLE_NAME` e `--DATABASE` corretos; retorna `JobRunId` |
| `test_inicia_job_com_year` | `--YEAR` presente nos argumentos quando `year` é passado |

### `TestGetResolvedOption`

| Teste | O que verifica |
|---|---|
| `test_delegates_to_getResolvedOptions` | Delega ao `getResolvedOptions` do AWS Glue e retorna o resultado |

### `TestGetParametersGlue`

| Teste | O que verifica |
|---|---|
| `test_returns_all_required_args` | Retorna `S3_BUCKET_SPEC`, `DB_UNIFIED`, `TABLE_NAME` e `GLUE_DATA_QUALITY_JOB_NAME` entre os argumentos obrigatórios |

## Como executar

```bash
# Apenas os testes do glue_agg
pytest test/glue_agg/ -v

# Com cobertura
pytest test/glue_agg/ --cov=app/glue_agg --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).
