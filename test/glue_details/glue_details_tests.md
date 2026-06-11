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
| `test_fetches_api_key_once` | Secrets Manager é chamado exatamente uma vez |
| `test_queries_athena_for_ids` | `fetch_ids_from_sot` é chamado com `media_type`, `year` e `database` corretos |
| `test_writes_details_table` | Tabela `tb_details_{media_type}_tmdb` é gravada na SOT |
| `test_writes_watch_providers_table` | Tabela `tb_watch_providers_{media_type}_tmdb` é gravada na SOT |
| `test_triggers_dq_for_details` | DQ é acionado para a tabela de detalhes |
| `test_triggers_dq_for_watch_providers` | DQ é acionado para a tabela de watch providers |

### Acionamento condicional do Glue AGG

| Teste | O que verifica |
|---|---|
| `test_triggers_agg_on_last_tv_year` | AGG é acionado quando `media_type="tv"` e `year == end_year` |
| `test_does_not_trigger_agg_for_movie` | AGG **não** é acionado para `media_type="movie"` |
| `test_does_not_trigger_agg_for_tv_non_last_year` | AGG **não** é acionado para séries quando `year != end_year` |
| `test_agg_triggered_exactly_once` | AGG é acionado no máximo uma vez por execução |

## Casos de teste — `test_utils.py`

Testa as funções individuais:

- `_tmdb_get`: retry com backoff exponencial em caso de erro HTTP (429, 500), sucesso após N tentativas
- `collect_and_write_details`: chamadas paralelas retornam o DataFrame esperado, IDs inválidos são ignorados
- `collect_and_write_watch_providers`: apenas provedores do Brasil (`BR`) são extraídos
- `fetch_ids_from_sot`: query Athena monta SQL correto, deduplicação funciona
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
