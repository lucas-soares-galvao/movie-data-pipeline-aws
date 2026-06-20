# Testes — glue_details

## O que é testado

Testa a função `main()` em `app/glue_details/main.py` e as funções utilitárias em `app/glue_details/src/utils.py`. O foco é verificar: coleta paralela de detalhes via API TMDB, lógica de acionamento condicional do Glue AGG (apenas na última execução) e escrita das tabelas de detalhes e watch providers na SOT. Todas as dependências externas (Athena, Secrets Manager, API TMDB, S3) são substituídas por **mocks** — objetos falsos que simulam o comportamento esperado sem fazer chamadas reais, mantendo os testes rápidos, gratuitos e isolados.

## Estrutura

```
test/glue_details/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes da função main()
└── test_utils.py             # Testes das funções utilitárias
```

## Fixtures (`conftest.py`)

| Fixture | Tipo | Descrição |
|---|---|---|
| `mock_ids` | `list[int]` | Lista de IDs simulados retornados pelo Athena |
| `mock_tmdb_response` | `dict` | Resposta simulada da API TMDB (runtime, seasons, etc.) |
| `mock_watch_providers_response` | `dict` | Resposta simulada de watch providers BR |
| `mock_boto3` | `MagicMock` | Substitui Secrets Manager e Glue client |
| `mock_awswrangler` | `MagicMock` | Substitui consultas Athena e escrita Parquet |

## Casos de teste — `test_main.py`

### Fluxo principal

| Teste | O que verifica |
|---|---|
| `test_fetches_api_key_from_secrets_manager` | Secrets Manager é chamado exatamente uma vez com o ARN correto |
| `test_fetches_ids_for_movie_using_discover_movie_table` | `fetch_ids_from_sot` é chamado com a tabela de discover de filmes |
| `test_fetches_ids_for_tv_using_discover_tv_table` | `fetch_ids_from_sot` é chamado com a tabela de discover de séries |
| `test_collect_called_once_for_movie` | `collect_and_write_details` é chamado com `content_type="movie"` e os IDs corretos |
| `test_collect_called_once_for_tv` | `collect_and_write_details` é chamado com `content_type="tv"` e os IDs corretos |
| `test_collect_watch_providers_called_with_correct_args_for_movie` | `collect_and_write_watch_providers` recebe tabela e ano corretos (movie) |
| `test_collect_watch_providers_called_with_correct_args_for_tv` | `collect_and_write_watch_providers` recebe tabela e ano corretos (tv) |
| `test_triggers_data_quality_twice_for_details_and_watch_providers` | DQ é acionado uma vez para cada tabela gravada |
| `test_skip_collect_details_when_no_new_ids` | `collect_and_write_details` **não** é chamado quando todos os IDs já existem no mês atual |
| `test_skip_collect_watch_providers_when_no_stale_ids` | `collect_and_write_watch_providers` **não** é chamado quando não há IDs stale |

### Acionamento condicional do repair e do Glue AGG

| Teste | O que verifica |
|---|---|
| `test_triggers_agg_when_tv_and_last_year` | AGG é acionado quando `media_type="tv"` e `year == end_year` |
| `test_repair_called_before_agg_when_tv_and_last_year` | Os três repairs são chamados na ordem `discover → watch_providers → details → agg` quando tv+end_year |
| `test_repair_called_for_movie_at_last_year` | `repair_details_duplicates` é chamado para `media_type="movie"` quando `year == end_year` |
| `test_repair_not_called_when_not_last_year` | Nenhum dos três repairs é chamado quando `year != end_year` |
| `test_repair_discover_duplicates_called_at_last_year` | `repair_discover_duplicates` é chamado com os argumentos corretos quando `year == end_year` |
| `test_repair_watch_providers_duplicates_called_at_last_year` | `repair_watch_providers_duplicates` é chamado com os argumentos corretos quando `year == end_year` |
| `test_does_not_trigger_agg_for_movie` | AGG **não** é acionado para `media_type="movie"` |
| `test_does_not_trigger_agg_for_tv_non_last_year` | AGG **não** é acionado para séries quando `year != end_year` |

## Casos de teste — `test_utils.py`

Testa as funções individuais:

- `tmdb_get` (de `shared_utils.tmdb_api`): retry com backoff exponencial em caso de erro HTTP (429, 500), sucesso após N tentativas
- `fetch_ids_from_sot`: query Athena monta SQL correto com filtro de ano
- `fetch_existing_ids_from_details`: SQL **não** contém filtro de `year` — detecta IDs processados em qualquer partição no mês atual; retorna `[]` em caso de erro (tabela inexistente na primeira execução)
- `fetch_ids_stale_watch_providers`: SQL usa LEFT JOIN e condição mensal; retorna `[]` em caso de erro
- `collect_and_write_details`: chamadas paralelas retornam o DataFrame esperado, IDs inválidos são ignorados; merge com dados existentes preserva IDs fora do batch e substitui IDs re-escritos; `drop_duplicates` garante unicidade no DataFrame antes da escrita; usa `mode="overwrite_partitions"`; falha no `read_parquet` grava apenas novos registros sem erro
- `repair_details_duplicates` (`TestRepairDetailsDuplicates`): sem duplicatas → não reescreve; S3 inacessível → não propaga exceção; partição vazia → não reescreve; com duplicatas → mantém `dt_processamento` mais recente por ID; usa `overwrite_partitions`
- `repair_discover_duplicates` (`TestRepairDiscoverDuplicates`): sem duplicatas → não reescreve; S3 inacessível → não propaga exceção; partição vazia → não reescreve; com duplicatas → mantém registro de maior `popularity`; usa `overwrite_partitions`
- `repair_watch_providers_duplicates` (`TestRepairWatchProvidersDuplicates`): sem duplicatas → não reescreve; S3 inacessível → não propaga exceção; com duplicatas → deduplicação pela chave `(id, provider_type, provider_id)`, mantendo `dt_atualizacao` mais recente; rebranding de provider (mesmo `provider_id`, nomes distintos) é tratado como duplicata; usa `overwrite_partitions`
- `collect_and_write_watch_providers` (`TestCollectAndWriteWatchProviders`): grava com partição `["year"]`; não escreve quando nenhum provedor é encontrado; IDs que falham na API são pulados sem propagar exceção; valor do ano é preservado no DataFrame gravado

As classes abaixo testam funções auxiliares de mais baixo nível que o doc anterior não cobria:

### `TestFetchTmdbDetails`

| Teste | O que verifica |
|---|---|
| `test_calls_movie_endpoint` | URL contém `/movie/{id}` para `content_type="movie"` |
| `test_calls_tv_endpoint` | URL contém `/tv/{id}` para `content_type="tv"` |
| `test_returns_json_response` | Retorna o JSON da resposta HTTP sem transformação |

### `TestFetchTmdbWatchProviders`

| Teste | O que verifica |
|---|---|
| `test_calls_movie_watch_providers_endpoint` | URL contém `/movie/{id}/watch/providers` |
| `test_calls_tv_watch_providers_endpoint` | URL contém `/tv/{id}/watch/providers` |
| `test_returns_br_section` | Retorna apenas o dicionário da seção `BR` do payload da API |

### `TestParseWatchProviders`

| Teste | O que verifica |
|---|---|
| `test_returns_empty_list_for_empty_br_data` | Retorna `[]` quando não há dados de BR |
| `test_generates_one_record_per_flatrate_provider` | Gera um registro por provedor `flatrate`, com `provider_type`, `provider_name`, `id` e `year` corretos |
| `test_generates_records_for_multiple_provider_types` | Processa `flatrate`, `rent` e `buy` gerando registros distintos por tipo |
| `test_ignores_providers_without_name` | Provedores sem `provider_name` são ignorados |

### `TestTriggerDataQuality`

| Teste | O que verifica |
|---|---|
| `test_starts_dq_job_with_table_database_and_year` | `start_job_run` chamado com `--TABLE_NAME`, `--DATABASE` e `--YEAR` corretos |
| `test_returns_job_run_id` | Retorna o `JobRunId` da resposta do Glue |

### `TestGetResolvedOption`

| Teste | O que verifica |
|---|---|
| `test_delegates_to_getResolvedOptions` | Delega ao `getResolvedOptions` do AWS Glue e retorna o resultado |

### `TestGetParametersGlue`

| Teste | O que verifica |
|---|---|
| `test_returns_all_required_args` | Retorna os parâmetros obrigatórios do job (`S3_BUCKET_SOT`, databases, tabelas de discover e details, `TABLE_WATCH_PROVIDERS_*`, `AGG_JOB_NAME`, etc.) |

### `TestGetTmdbApiKey`

| Teste | O que verifica |
|---|---|
| `test_retorna_chave_do_secrets_manager` | Lê o segredo pelo ARN fornecido e retorna o valor de `tmdb_api_key` |

## Como executar

```bash
# Apenas os testes do glue_details
pytest test/glue_details/ -v

# Com cobertura
pytest test/glue_details/ --cov=app/glue_details --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).
