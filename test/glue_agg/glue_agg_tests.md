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

Testa as funções individuais:

- `run_athena_query`: query SQL montada corretamente com os databases passados; DataFrame retornado com as colunas esperadas; SQL contém CTEs `movie_wp_recent` / `tv_wp_recent` com `DENSE_RANK() OVER (...ORDER BY CAST(year AS INTEGER) DESC)` para dedup de watch providers; SQL contém `spec_raw`, `spec_deduped` e `PARTITION BY id, media_type` para dedup final; SQL contém CTE `now_playing` com `LEFT JOIN` em `tb_now_playing_movie_tmdb` gerando as colunas `in_theaters`, `theater_start_date` e `theater_end_date`
- `write_parquet_to_spec`: chamada ao `awswrangler.s3.to_parquet` com `mode="overwrite"` e `partition_cols=["media_type", "year"]`
- `trigger_data_quality` (`TestTriggerDataQuality`): sem `year` → argumento `--YEAR` ausente no `start_job_run`; com `year` → argumento `--YEAR` presente; retorna `JobRunId` correto
- `get_parameters_glue`: inclui `GLUE_DATA_QUALITY_JOB_NAME` nos argumentos requeridos

## Como executar

```bash
# Apenas os testes do glue_agg
pytest test/glue_agg/ -v

# Com cobertura
pytest test/glue_agg/ --cov=app/glue_agg --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto.
