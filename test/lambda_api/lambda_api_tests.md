# Testes — lambda_api

## O que é testado

Testa a função `lambda_handler` em `app/lambda_api/main.py` e as funções utilitárias em `app/lambda_api/src/utils.py`. Os testes são unitários: todas as dependências externas (AWS, TMDB, S3) são substituídas por mocks, garantindo execução offline, rápida e determinística.

## Estrutura

```
test/lambda_api/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes do lambda_handler
└── test_utils.py             # Testes das funções utilitárias
```

## Fixtures (`conftest.py`)

| Fixture | Tipo | Descrição |
|---|---|---|
| `mock_boto3` | Mock | Substitui o cliente boto3 (S3, Glue, Secrets Manager) |
| `mock_requests` | Mock | Substitui chamadas HTTP à API TMDB |
| Variáveis de ambiente | `os.environ` | `TMDB_SECRET_ARN`, `GLUE_ETL_JOB_NAME`, `S3_BUCKET_SOR` definidos antes do import |

## Casos de teste — `test_main.py`

### `TestLambdaHandler` — comportamento base do handler

| Teste | O que verifica |
|---|---|
| `test_retorna_status_200_para_movie` | Handler retorna `{"statusCode": 200}` para evento do tipo `movie` |
| `test_retorna_status_200_para_tv` | Handler retorna `{"statusCode": 200}` para evento do tipo `tv` |
| `test_busca_api_key_uma_unica_vez` | Secrets Manager é chamado exatamente uma vez, independente do número de anos |
| `test_collect_genre_chamado_com_tipo_movie` | `collect_genre_data` é chamado com `content_type="movie"` |
| `test_collect_configuration_chamado_com_tipo_tv` | `collect_configuration_data` é chamado com `content_type="tv"` |
| `test_loop_executa_para_cada_ano` | `collect_discover_data` é chamado uma vez por ano no range `[start_year, current_year]` |
| `test_collect_discover_usa_folder_correto_para_movie` | Discover usa path `tmdb/discover/movie` |
| `test_collect_discover_usa_folder_correto_para_tv` | Discover usa path `tmdb/discover/tv` |
| `test_glue_recebe_argumentos_padronizados` | Glue ETL é acionado com `MEDIA_TYPE`, `DATABASE` e `table_name` corretos para cada tabela |
| `test_glue_acionado_para_genre_e_configuration_sem_year` | Glue de genre/configuration não recebe argumento `year` |
| `test_glue_no_loop_recebe_year_e_table_type_corretos` | Glue de discover recebe `year` e `table_type="discover"` para cada ano |
| `test_glue_discover_recebe_end_year` | Todas as chamadas de discover repassam `end_year` |

### `TestSkipDaily` — flag `skip_daily=True`

| Teste | O que verifica |
|---|---|
| `test_skip_daily_nao_chama_collect_discover` | `collect_discover_data` não é chamado |
| `test_skip_daily_ainda_coleta_genre_configuration_watch_providers` | Coleta de referências continua normalmente |
| `test_skip_daily_glue_acionado_apenas_para_referencias` | Glue é acionado 3 vezes (genre, configuration, watch_providers_ref), sem discover |
| `test_skip_daily_retorna_status_200` | Handler retorna 200 mesmo com skip_daily |

### `TestOnlyDiscover` — flag `only_discover=True`

| Teste | O que verifica |
|---|---|
| `test_only_discover_pula_genre` | `collect_genre_data` não é chamado |
| `test_only_discover_pula_configuration` | `collect_configuration_data` não é chamado |
| `test_only_discover_pula_watch_providers_ref` | `collect_watch_providers_ref` não é chamado |
| `test_only_discover_executa_loop_normalmente` | Loop de discover roda normalmente, Glue acionado 1x por ano |
| `test_only_discover_retorna_status_200` | Handler retorna 200 com only_discover |

### `TestNowPlaying` — coleta de filmes em cartaz

| Teste | O que verifica |
|---|---|
| `test_collect_now_playing_chamado_quando_tabela_presente` | `collect_now_playing_data` é chamado quando `table_now_playing_movie` está no evento |
| `test_collect_now_playing_nao_chamado_sem_tabela` | `collect_now_playing_data` **não** é chamado quando `table_now_playing_movie` está ausente |
| `test_glue_acionado_com_table_type_now_playing` | Glue ETL é acionado com `table_type="now_playing"` e `table_name` correto após a coleta |

## Casos de teste — `test_utils.py`

Testa individualmente as funções de `src/utils.py`: coleta da API TMDB, salvamento no S3 e acionamento do Glue. Verifica contratos de chamada (argumentos corretos passados para boto3 e requests) e tratamento de erros (API retorna vazio, falha de rede).

### `collect_now_playing_data`

| Teste | O que verifica |
|---|---|
| `test_dados_salvos_incluem_datas_teatrais` | Cada registro salvo contém `theater_start_date` e `theater_end_date` extraídos do campo `dates` da API |
| `test_salva_uma_pagina_por_arquivo` | Número de arquivos salvos no S3 corresponde ao número de páginas retornadas |
| `test_salva_arquivo_mesmo_com_uma_pagina` | Funciona corretamente quando a API retorna apenas uma página |
| `test_s3_key_usa_prefixo_now_playing` | Chave S3 segue o padrão `tmdb/now_playing/movie/pagina_001.json` |

## Como executar

```bash
# Apenas os testes da lambda_api
pytest test/lambda_api/ -v

# Com cobertura
pytest test/lambda_api/ --cov=app/lambda_api --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto. O CI falha se a cobertura ficar abaixo desse limite.
