# Testes — glue_etl

## O que é testado

Testa a função `main()` em `app/glue_etl/main.py` e as funções utilitárias em `app/glue_etl/src/utils.py`. Os testes verificam o comportamento da orquestração para cada valor de `TABLE_TYPE` e o acionamento condicional do Glue Details. Todas as dependências externas (S3, Glue Catalog, Athena) são substituídas por **mocks** — objetos falsos que simulam o comportamento esperado sem fazer chamadas reais à AWS, mantendo os testes rápidos, gratuitos e isolados.

## Estrutura

```
test/glue_etl/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes da função main() por TABLE_TYPE
└── test_utils.py             # Testes das funções utilitárias
```

## Fixtures (`conftest.py`)

| Fixture | Tipo | Descrição |
|---|---|---|
| `_BASE` (constante) | `dict` | Argumentos comuns a todos os runs (buckets, nomes de jobs, databases) |
| Mocks via `patch.object` | `MagicMock` | `read_from_sor`, `write_parquet_to_sot`, `trigger_data_quality`, `trigger_details` substituídos por mock em cada teste |

## Casos de teste — `test_main.py`

### `TestRunDiscover` — `TABLE_TYPE="discover"`

| Teste | O que verifica |
|---|---|
| `test_calls_read_from_sor_with_discover_args` | `read_from_sor` chamado com `(bucket, media_type, "discover", year)` |
| `test_writes_to_discover_table_with_year_partition` | `write_parquet_to_sot` chamado com `partition_cols=["year"]` e `mode="overwrite_partitions"` |
| `test_tv_media_type_forwarded_to_read_from_sor` | Para `MEDIA_TYPE="tv"`, lê e escreve com os argumentos corretos de tv |
| `test_write_is_called_exactly_once` | `write_parquet_to_sot` é chamado exatamente uma vez por execução |
| `test_triggers_data_quality_with_year` | DQ é acionado com `year` correto para tabelas discover |

### `TestRunGenre` — `TABLE_TYPE="genre"`

| Teste | O que verifica |
|---|---|
| `test_calls_read_from_sor_with_genre_args` | `read_from_sor` chamado com `year=None` |
| `test_writes_to_genre_table_without_partition` | `write_parquet_to_sot` com `partition_cols=None` e `mode="overwrite"` |
| `test_triggers_data_quality_without_year` | DQ acionado sem `year` para genre |

### `TestRunConfiguration` — `TABLE_TYPE="configuration"`

| Teste | O que verifica |
|---|---|
| `test_calls_read_from_sor_with_configuration_args` | `read_from_sor` chamado com `year=None` |
| `test_writes_to_configuration_table_without_partition` | Escrita sem partição, mode `overwrite` |
| `test_tv_uses_configuration_countries_table` | Para `MEDIA_TYPE="tv"`, usa tabela `tb_configuration_countries_tmdb` |
| `test_triggers_data_quality_without_year` | DQ acionado sem `year` para configuration |

### `TestRunNowPlaying` — `TABLE_TYPE="now_playing"`

| Teste | O que verifica |
|---|---|
| `test_calls_read_from_sor_with_now_playing_args` | `read_from_sor` chamado com `(bucket, "movie", "now_playing", None)` — sem `year` |
| `test_writes_to_now_playing_table_without_partition` | `write_parquet_to_sot` chamado com `partition_cols=None` e `mode="overwrite"` |
| `test_triggers_data_quality_without_year` | DQ acionado com `year=None` para now_playing |

### `TestTriggerDetails` — acionamento condicional do Glue Details

| Teste | O que verifica |
|---|---|
| `test_details_triggered_for_movie_discover` | Details acionado com `media_type="movie"`, `year` e `end_year` corretos |
| `test_details_triggered_for_tv_discover` | Details acionado com `media_type="tv"` e databases corretos |
| `test_details_not_triggered_for_genre_tv` | Details **não** é acionado para `TABLE_TYPE="genre"` |
| `test_details_triggered_exactly_once_per_discover_run` | Details acionado exatamente uma vez por execução de discover |

## Casos de teste — `test_utils.py`

Testa individualmente as funções utilitárias: leitura do SOR, escrita na SOT com AWS Wrangler, normalização de nomes de plataformas de streaming e acionamento dos jobs de DQ e Details. Verifica argumentos passados para `awswrangler` e `boto3`.

### `read_from_sor` — `table_type="now_playing"`

| Teste | O que verifica |
|---|---|
| `test_now_playing_lê_do_path_correto` | `awswrangler.s3.read_json` chamado com `path="s3://bucket/tmdb/now_playing/movie/"` |
| `test_now_playing_remove_duplicatas_por_id` | Registros com mesmo `id` são deduplicados antes de retornar |
| `test_now_playing_retorna_dataframe_correto` | DataFrame retornado contém as colunas e valores esperados |

## Como executar

```bash
# Apenas os testes do glue_etl
pytest test/glue_etl/ -v

# Com cobertura
pytest test/glue_etl/ --cov=app/glue_etl --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto.
