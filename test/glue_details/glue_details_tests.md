# Testes — glue_details

## O que é testado

Testa a função `main()` em `app/glue_details/main.py` e as funções utilitárias em `app/glue_details/src/utils.py`. O foco é verificar: coleta paralela de detalhes via API TMDB, lógica de acionamento condicional do Glue AGG (apenas na última execução) e escrita das tabelas de detalhes e watch providers na SOT. Todas as dependências externas são mockadas.

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

### Acionamento condicional do Glue AGG

| Teste | O que verifica |
|---|---|
| `test_triggers_agg_when_tv_and_last_year` | AGG é acionado quando `media_type="tv"` e `year == end_year` |
| `test_does_not_trigger_agg_for_movie` | AGG **não** é acionado para `media_type="movie"` |
| `test_does_not_trigger_agg_for_tv_non_last_year` | AGG **não** é acionado para séries quando `year != end_year` |

## Casos de teste — `test_utils.py`

Testa as funções individuais:

- `_tmdb_get`: retry com backoff exponencial em caso de erro HTTP (429, 500), sucesso após N tentativas
- `fetch_ids_from_sot`: query Athena monta SQL correto com filtro de ano
- `fetch_existing_ids_from_details`: SQL filtra pelo ano e por `date_trunc('month', current_date)`; retorna `[]` em caso de erro (tabela inexistente na primeira execução)
- `fetch_ids_stale_watch_providers`: SQL usa LEFT JOIN e condição mensal; retorna `[]` em caso de erro
- `collect_and_write_details`: chamadas paralelas retornam o DataFrame esperado, IDs inválidos são ignorados; merge com dados existentes preserva IDs fora do batch e substitui IDs re-escritos; usa `mode="overwrite_partitions"`; falha no `read_parquet` grava apenas novos registros sem erro
- `collect_and_write_watch_providers`: apenas provedores do Brasil (`BR`) são extraídos
- `trigger_agg`: argumentos passados ao `start_job_run` do Glue estão corretos

## Como executar

```bash
# Apenas os testes do glue_details
pytest test/glue_details/ -v

# Com cobertura
pytest test/glue_details/ --cov=app/glue_details --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto.
