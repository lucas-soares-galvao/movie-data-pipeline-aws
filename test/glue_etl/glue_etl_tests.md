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

`conftest.py` não define fixtures pytest — é um bootstrap de import/ambiente:

| Item | Descrição |
|---|---|
| Ajuste de `sys.path` | Insere `app/glue_etl/` no início de `sys.path`, permitindo `from src.utils import ...` como no runtime do Glue |
| Stub de `awsglue` | Registra `awsglue`/`awsglue.utils` em `sys.modules` com `getResolvedOptions` como `MagicMock()` e `GlueArgumentError = Exception` |

## Casos de teste — `test_main.py`

Usa a constante `_BASE` (dict com args comuns: buckets, nomes de jobs, databases) definida em `test_main.py`, e mocks via `patch.object` — `read_from_sor`, `write_parquet_to_sot`, `trigger_glue_job` (de `shared_utils.triggers`) são substituídos localmente em cada teste.

### `TestRunDiscover` — `TABLE_TYPE="discover"`

| Teste | O que verifica |
|---|---|
| `test_calls_read_from_sor_with_discover_args` | `read_from_sor` chamado com `(bucket, media_type, "discover", year)` nos 4 primeiros posicionais, mais um `translate_fn` callable como 5º (fallback via AWS Translate, montado uma vez em `main()`) |
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
| `test_tv_uses_configuration_countries_table` | Para `MEDIA_TYPE="tv"`, usa tabela `tb_tmdb_configuration_countries_{env}` |
| `test_triggers_data_quality_without_year` | DQ acionado sem `year` para configuration |
| `test_passes_s3_bucket_sot_and_table_name_for_translation_cache` | `read_from_sor` recebe `s3_bucket_sot`/`table_name` nos kwargs — usados para reaproveitar `name_pt` já gravado na SOT (cache de tradução) |

### `TestRunNowPlaying` — `TABLE_TYPE="now_playing"`

| Teste | O que verifica |
|---|---|
| `test_calls_read_from_sor_with_now_playing_args` | `read_from_sor` chamado com `(bucket, "movie", "now_playing", None)` — sem `year` |
| `test_writes_to_now_playing_table_without_partition` | `write_parquet_to_sot` chamado com `partition_cols=None` e `mode="overwrite"` |
| `test_triggers_data_quality_without_year` | DQ acionado com `year=None` para now_playing |

### `TestTriggerDetails` — acionamento condicional do Glue Details

| Teste | O que verifica |
|---|---|
| `test_details_triggered_for_movie_discover` | Details acionado com `media_type="movie"`, `year`, `end_year` e `TRANSLATE_PROVIDER="aws"` (default) corretos |
| `test_details_triggered_for_tv_discover` | Details acionado com `media_type="tv"`, databases e `TRANSLATE_PROVIDER="aws"` (default) corretos |
| `test_details_not_triggered_for_genre_tv` | Details **não** é acionado para `TABLE_TYPE="genre"` |
| `test_translate_provider_repassado_ao_details` | `TRANSLATE_PROVIDER` informado explicitamente (ex.: backfill manual com `"google"`) é repassado ao Details, não apenas o default `"aws"` |
| `test_details_triggered_exactly_once_per_discover_run` | Details acionado exatamente uma vez por execução de discover |

## Casos de teste — `test_utils.py`

Testa individualmente as funções utilitárias: leitura do SOR por `table_type`, escrita na SOT e normalização de nomes de plataformas. Verifica argumentos passados para `awswrangler` e `boto3`. Os triggers de jobs Glue são testados em `test/shared_src/test_triggers.py`.

- **`TestReadFromSorDiscover`** (8 testes): path S3 correto (`tmdb/discover/{media_type}/ano={year}/`) para movie e tv; coluna `year` adicionada ao DataFrame com valor correto; `overview_idioma_detectado` calculado a partir de `overview` via `detect_fn`; `overview_traduzido_pt_br` — booleano puramente derivado de `overview_idioma_detectado == "pt"`, **sem nenhuma tradução** (o `overview` já vem pt-BR nativo do TMDB via `lambda_api`) — `True`/`False` conforme o idioma detectado; guard de schema — sem a coluna `overview` (fixture mínima/legado), nem `overview_idioma_detectado` nem `overview_traduzido_pt_br` são criadas
- **`TestReadFromSorGenre`** (3 testes): chave S3 correta para movie (`generos_filmes.json`) e tv (`generos_series.json`); retorna DataFrame da lista JSON
- **`TestReadFromSorWatchProvidersRef`** (4 testes): chave S3 correta para movie/tv; coluna `canonical_name` adicionada via `derive_canonical_name`; override aplicado (ex: "Paramount Plus" → "Paramount+")
- **`TestReadFromSorConfiguration`** (6 testes): movie → `languages/idiomas.json`; tv → `countries/paises.json`; retorna DataFrame com colunas corretas; tv countries recebe coluna `name_pt` traduzida via `translate_text` (`shared_utils.traducao`, mockada em `src.utils.translate_text`); **cache de tradução:** quando `s3_bucket_sot`/`table_name` são passados e `english_name` é idêntico ao já gravado na SOT (`wr.s3.read_parquet` mockado), reaproveita `name_pt` sem chamar `translate_text` (`test_reaproveita_name_pt_quando_english_name_nao_mudou`); quando `english_name` mudou, traduz normalmente (`test_retraduz_quando_english_name_mudou`)
- **`TestAddNamePtCountries`** (9 testes): traduz `english_name` para pt-BR via `translate_text` (mockada); sem coluna `english_name` retorna inalterado (nenhuma coluna nova, incluindo `name_idioma_detectado_en`/`_pt`/`name_tentativas_traducao`); `english_name` vazio/nulo resulta em `name_pt` nulo; com `previous_df` e fonte idêntica reaproveita `name_pt` sem chamar `translate_text`; com fonte diferente traduz normalmente; `name_idioma_detectado_en` calculado a partir de `english_name` (via `detect_fn` mockado); `name_idioma_detectado_pt` é `"pt"` após tradução bem-sucedida; copia `english_name` direto para `name_pt` sem chamar tradução quando o idioma já é detectado como `"pt"` (mesma otimização do `glue_details` contra retradução infinita, impacto prático baixo aqui)
- **`TestAddNamePtLanguages`** (7 testes): traduz `english_name` dos idiomas para pt-BR via `translate_text` (mockada); sem coluna `english_name` retorna inalterado; `english_name` vazio/nulo resulta em `name_pt` nulo; com `previous_df` e fonte idêntica reaproveita `name_pt` sem chamar `translate_text` (detecção mockada — `langdetect` real não é confiável para nomes curtos como "Inglês"); com fonte diferente traduz normalmente; `name_idioma_detectado_en` calculado a partir de `english_name`; copia direto sem chamar tradução quando idioma já detectado como `"pt"`
- **`TestReadFromSorConfigurationLanguages`** (1 teste): movie configuration recebe coluna `name_pt` traduzida via `translate_text` (mockada)
- **`TestReadExistingConfiguration`** (2 testes): retorna o DataFrame lido via `wr.s3.read_parquet` (path `s3://{bucket}/tmdb/{table_name}/`); retorna `DataFrame()` vazio quando a leitura falha (tabela ainda não existe)
- **`TestReadFromSorNowPlaying`** (3 testes): path S3 `tmdb/now_playing/movie/`; deduplica por `id`; retorna DataFrame
- **`TestWriteParquetToSot`** (4 testes): `awswrangler.s3.to_parquet` chamado com `partition_cols`, `mode` e `path` (`s3://{bucket}/tmdb/{table_name}/`) corretos; `mode` customizado repassado
- **`TestDeriveCanonicalName`** (12 testes): remoção de sufixos ("Standard with Ads", "Premium", "Plus Premium", "Amazon Channel"); overrides manuais ("Paramount Plus" → "Paramount+", "Claro video" → "Claro Video"); composição ("Paramount Plus Premium" → "Paramount+", "MGM Plus Amazon Channel" → "MGM+")
- **`TestGetParametersGlue`** (5 testes): retorna args obrigatórios; inclui `YEAR`/`END_YEAR` quando disponíveis nos argumentos do job; omite quando ausentes (sem quebrar); `TRANSLATE_PROVIDER` tem default `"aws"` quando ausente e é lido corretamente quando fornecido (opcional, mesmo padrão de `YEAR`/`END_YEAR` — `getResolvedOptions` levanta `SystemExit` para argumento ausente)

## Como executar

```bash
# Apenas os testes do glue_etl
pytest test/glue_etl/ -v

# Com cobertura
pytest test/glue_etl/ --cov=app/glue_etl --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).
