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

Testa individualmente as funções utilitárias: leitura do SOR por `table_type`, escrita na SOT, normalização de nomes de plataformas e acionamento dos jobs de DQ, Details e AGG. Verifica argumentos passados para `awswrangler` e `boto3`.

- **`TestReadFromSorDiscover`** (4 testes): path S3 correto (`tmdb/discover/{media_type}/ano={year}/`) para movie e tv; coluna `year` adicionada ao DataFrame com valor correto
- **`TestReadFromSorGenre`** (3 testes): chave S3 correta para movie (`generos_filmes.json`) e tv (`generos_series.json`); retorna DataFrame da lista JSON
- **`TestReadFromSorWatchProvidersRef`** (4 testes): chave S3 correta para movie/tv; coluna `canonical_name` adicionada via `derive_canonical_name`; override aplicado (ex: "Paramount Plus" → "Paramount+")
- **`TestReadFromSorConfiguration`** (3 testes): movie → `languages/idiomas.json`; tv → `countries/paises.json`; retorna DataFrame com colunas corretas
- **`TestReadFromSorNowPlaying`** (3 testes): path S3 `tmdb/now_playing/movie/`; deduplica por `id`; retorna DataFrame
- **`TestWriteParquetToSot`** (4 testes): `awswrangler.s3.to_parquet` chamado com `partition_cols`, `mode` e `path` (`s3://{bucket}/tmdb/{table_name}/`) corretos; `mode` customizado repassado
- **`TestDeriveCanonicalName`** (12 testes): remoção de sufixos ("Standard with Ads", "Premium", "Plus Premium", "Amazon Channel"); overrides manuais ("Paramount Plus" → "Paramount+", "Claro video" → "Claro Video"); composição ("Paramount Plus Premium" → "Paramount+", "MGM Plus Amazon Channel" → "MGM+")
- **`TestTriggerAgg`** (2 testes): `start_job_run` com `JobName` correto; retorna `JobRunId`
- **`TestTriggerDataQuality`** (4 testes): argumentos `TABLE_NAME` e `DATABASE` corretos; `--YEAR` presente quando fornecido e ausente quando não; retorna `JobRunId`
- **`TestTriggerDetails`** (4 testes): todos os argumentos obrigatórios (`MEDIA_TYPE`, `YEAR`, `END_YEAR`, `DATABASE`) passados ao `start_job_run`; retorna `JobRunId`
- **`TestGetResolvedOption`** (1 teste): delega corretamente ao `getResolvedOptions` do Glue runtime
- **`TestGetParametersGlue`** (3 testes): retorna args obrigatórios; inclui `YEAR`/`END_YEAR` quando disponíveis nos argumentos do job; omite quando ausentes (sem quebrar)

## Como executar

```bash
# Apenas os testes do glue_etl
pytest test/glue_etl/ -v

# Com cobertura
pytest test/glue_etl/ --cov=app/glue_etl --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto.
