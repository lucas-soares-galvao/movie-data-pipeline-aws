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

### `TestTmdbGet`

| Teste | O que verifica |
|---|---|
| `test_retorna_json_em_sucesso` | Retorna JSON correto em resposta 200, sem chamar `time.sleep` |
| `test_retry_em_status_transiente_e_retorna_em_sucesso` | Faz 2 tentativas e retorna o JSON na segunda, quando a primeira falha com 500 |
| `test_retry_em_429_usa_retry_after` | Espera pelo menos o tempo indicado no header `Retry-After` ao receber 429 |
| `test_retry_em_connection_error_e_retorna_em_sucesso` | Tenta novamente após `ConnectionError` e retorna em sucesso |
| `test_levanta_apos_esgotar_tentativas_http` | Levanta `HTTPError` após esgotar 3 tentativas com erro HTTP |
| `test_levanta_apos_esgotar_tentativas_connection` | Levanta `ConnectionError` após esgotar 3 tentativas com falha de rede |

### `TestGetTmdbApiKey`

| Teste | O que verifica |
|---|---|
| `test_retorna_chave_do_secrets_manager` | Lê o segredo pelo ARN fornecido e retorna o valor de `tmdb_api_key` do JSON do Secrets Manager |

### `TestFetchTmdbData`

| Teste | O que verifica |
|---|---|
| `test_busca_filmes_com_url_correta` | URL contém `discover/movie` para `content_type="movie"` |
| `test_busca_series_com_url_correta` | URL contém `discover/tv` para `content_type="tv"` |
| `test_filme_usa_parametro_primary_release_year` | Parâmetro `primary_release_year` é incluído para filmes |
| `test_serie_usa_parametro_first_air_date_year` | Parâmetro `first_air_date_year` é incluído para séries |

### `TestSaveToS3`

| Teste | O que verifica |
|---|---|
| `test_salva_json_no_s3_com_parametros_corretos` | `put_object` chamado com `Bucket`, `Key` e `ContentType="application/json"` corretos |
| `test_conteudo_salvo_e_json_valido` | O corpo salvo pode ser desserializado como JSON e os dados são preservados |

### `TestTriggerGlueJob`

| Teste | O que verifica |
|---|---|
| `test_inicia_job_e_retorna_run_id` | Retorna o `JobRunId` da resposta do Glue |
| `test_argumentos_do_glue_contem_year_e_tabelas` | `--YEAR`, `--DATABASE`, `--TABLE_TYPE` e `--TABLE_NAME` presentes nos argumentos do Glue |
| `test_sem_year_nao_inclui_argumento_year` | `--YEAR` ausente quando chamado sem `year` (tabelas de referência) |
| `test_table_type_incluido_nos_argumentos_do_glue` | `--TABLE_TYPE` sempre repassado ao Glue |
| `test_table_name_incluido_nos_argumentos_do_glue` | `--TABLE_NAME` sempre repassado ao Glue |
| `test_discover_inclui_end_year` | `--END_YEAR` presente para chamadas de discover |
| `test_genre_nao_inclui_end_year` | `--END_YEAR` ausente para chamadas de genre/configuration |

### `TestFetchTmdbReference`

| Teste | O que verifica |
|---|---|
| `test_busca_endpoint_sem_params_extras` | URL contém o endpoint passado e retorna o payload correto |
| `test_busca_endpoint_com_params_extras` | Params extras (ex: `language`) são incluídos na requisição |

### `TestCollectGenreData`

| Teste | O que verifica |
|---|---|
| `test_movie_coleta_generos_de_filmes` | Usa endpoint `/genre/movie/list` e salva em `tmdb/genre/movie/generos_filmes.json` |
| `test_tv_coleta_generos_de_series` | Usa endpoint `/genre/tv/list` e salva em `tmdb/genre/tv/generos_series.json` |
| `test_movie_nao_coleta_dados_de_tv` | `content_type="movie"` não chama o endpoint de séries |

### `TestCollectConfigurationData`

| Teste | O que verifica |
|---|---|
| `test_movie_coleta_idiomas` | Usa `/configuration/languages` e salva em `tmdb/configuration/languages/idiomas.json` |
| `test_tv_coleta_paises` | Usa `/configuration/countries` e salva em `tmdb/configuration/countries/paises.json` |

### `TestCollectDiscoverData`

| Teste | O que verifica |
|---|---|
| `test_salva_todas_as_paginas_disponiveis` | Itera por todas as páginas disponíveis e chama `save_to_s3` uma vez por página |
| `test_para_quando_so_ha_uma_pagina` | Para corretamente quando `total_pages = 1` |
| `test_s3_key_segue_padrao_esperado` | Chave S3 segue o padrão `tmdb/discover/{type}/ano={ano}/pagina_NNN.json` |
| `test_salva_apenas_results` | Dados salvos no S3 são apenas o campo `results`, sem metadados de paginação |
| `test_nao_inclui_metadados_de_paginacao` | Não inclui `page`, `total_pages` ou `total_results` no payload salvo |

### `collect_watch_providers_ref`

9 testes verificando coleta de plataformas de streaming de referência: path S3 correto por `content_type` (movie/tv); JSON salvo no S3; múltiplas páginas processadas corretamente.

### `collect_now_playing_data`

| Teste | O que verifica |
|---|---|
| `test_pagina_unica_enriquece_com_datas_teatrais` | Registro salvo contém `theater_start_date` e `theater_end_date` extraídos do campo `dates` da API |
| `test_multiplas_paginas_salva_cada_uma` | Número de arquivos salvos no S3 corresponde ao número de páginas retornadas |
| `test_para_quando_page_maior_que_total_pages` | Paginação para quando `page > total_pages` retornado pela API |
| `test_s3_key_tem_formato_correto` | Chave S3 segue o padrão `tmdb/now_playing/movie/pagina_001.json` |

## Como executar

```bash
# Apenas os testes da lambda_api
pytest test/lambda_api/ -v

# Com cobertura
pytest test/lambda_api/ --cov=app/lambda_api --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto. O CI falha se a cobertura ficar abaixo desse limite.
