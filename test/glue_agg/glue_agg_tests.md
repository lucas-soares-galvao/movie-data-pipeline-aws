# Testes — glue_agg

## O que é testado

Testa a função `main()` em `app/glue_agg/main.py` e as funções utilitárias em `app/glue_agg/src/utils.py`. O ponto central é garantir que as três etapas do pipeline (query Athena → tradução → escrita na SPEC) ocorrem na **ordem correta** e com os argumentos certos. Todas as dependências externas são mockadas.

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
| `test_translation_called_between_query_and_write` | **Ordem garantida:** `run_athena_query` → `traduzir_colunas_en` → `write_parquet_to_spec` (usando `call_order[]`) |
| `test_translation_called_exactly_once` | `traduzir_colunas_en` é chamado exatamente uma vez |

> **Destaque:** `test_translation_called_between_query_and_write` usa uma lista compartilhada `call_order` nos side_effects dos três mocks para verificar a ordem de execução — garante que títulos sejam traduzidos *antes* de serem gravados na SPEC.

## Casos de teste — `test_utils.py`

Testa as funções individuais:

- `run_athena_query`: query SQL montada corretamente com os databases passados; DataFrame retornado com as colunas esperadas
- `traduzir_colunas_en`: apenas registros com `original_language="en"` são traduzidos; registros em outros idiomas permanecem inalterados; falhas na tradução não quebram o job
- `write_parquet_to_spec`: chamada ao `awswrangler.s3.to_parquet` com os parâmetros de particionamento corretos

## Como executar

```bash
# Apenas os testes do glue_agg
pytest test/glue_agg/ -v

# Com cobertura
pytest test/glue_agg/ --cov=app/glue_agg --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto.
