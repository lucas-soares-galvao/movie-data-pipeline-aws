# lambda_api — Coletor de Dados (TMDB)

## O que é

A Lambda API é o ponto de entrada do pipeline. É uma função serverless (sem servidor dedicado — você paga apenas pelo tempo em que ela roda) acionada automaticamente pelo **EventBridge** (serviço de agendamento da AWS, funciona como um cron) em dois agendamentos: diário (coleta só discover) e semanal (coleta também dados de referência). Ela busca dados de filmes e séries na API do TMDB, salva os resultados em S3 na camada **SOR** (dados brutos, sem transformação) e aciona o Glue ETL para cada lote.

## Por que existe

Isola a camada de ingestão (HTTP → S3) da camada de transformação (S3 → Parquet). Ao separar essa responsabilidade, é possível reprocessar ou modificar a coleta sem tocar nos jobs de transformação, e vice-versa.

## Como funciona

1. O EventBridge dispara a Lambda com um payload JSON indicando o tipo de mídia (`movie` ou `tv`) e os nomes das tabelas do Glue Catalog.
2. A Lambda busca a chave da API do TMDB no **Secrets Manager** (cofre de senhas da AWS — armazena credenciais com segurança, evitando que a chave fique exposta no código) — uma única vez por execução, independente de quantos anos existam.
3. Dependendo dos flags recebidos no evento:
   - **`only_discover=True`** (execução diária): pula gêneros, idiomas, países e plataformas de referência.
   - **`skip_daily=True`** (execução mensal de referências): pula o loop de discover.
   - Sem flags: coleta tudo.
4. Para dados de referência (gêneros, idiomas/países, plataformas): faz uma chamada à API e salva um único arquivo JSON no S3 SOR, depois aciona o Glue ETL.
5. Para dados de discover: itera por cada ano (`start_year` = ano atual − 1, até o ano atual), faz requisições paginadas à API, salva um arquivo JSON por ano no S3 SOR e aciona o Glue ETL para aquele ano.
6. Para filmes (`content_type="movie"`), após o loop de discover, coleta também os filmes em cartaz nos cinemas via `collect_now_playing_data()`: pagina o endpoint `/movie/now_playing`, extrai as datas da janela teatral (`theater_start_date`, `theater_end_date`) e salva os resultados no S3 SOR, depois aciona o Glue ETL com `table_type="now_playing"`. Esse passo é condicional: só ocorre se `table_now_playing` estiver presente no evento.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Evento JSON do EventBridge com `type`, nomes de tabelas e flags opcionais (`skip_daily`, `only_discover`) |
| **Leitura** | API TMDB (HTTP), Secrets Manager (chave de API) |
| **Escrita** | S3 SOR — `tmdb/discover/{movie|tv}/year={ano}/`, `tmdb/{genre|configuration|watch_providers_ref}/{movie|tv}/` e `tmdb/now_playing/movie/pagina_NNN.json` |
| **Aciona** | Glue ETL para cada tabela coletada (genre, configuration, watch_providers_ref, discover por ano, now_playing para filmes) |

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_tmdb_api_key(secret_arn)` | Lê a chave da API no Secrets Manager |
| `collect_genre_data(...)` | Coleta mapeamento de IDs → nomes de gêneros |
| `collect_configuration_data(...)` | Coleta lista de idiomas ou países |
| `collect_watch_providers_ref(...)` | Coleta lista de plataformas de streaming disponíveis |
| `collect_discover_data(...)` | Coleta filmes/séries populares de um ano (paginado) |
| `collect_now_playing_data(...)` | Coleta filmes em cartaz nos cinemas (paginado), extrai datas de janela teatral e salva no S3 SOR |
| `trigger_glue_job(job_name, client, args, ...)` | Aciona o Glue ETL com argumentos dinâmicos |

## Tecnologias

- **boto3** — integração com AWS (S3, Glue, Secrets Manager)
- **requests** — chamadas HTTP à API TMDB
- **EventBridge** — agendamento e disparo da função
