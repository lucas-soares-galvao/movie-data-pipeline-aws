# glue_details — Enriquecedor de Detalhes

## O que é

O Glue Details é o terceiro estágio do pipeline de dados. Acionado pelo Glue ETL após cada tabela `discover` ser processada, ele busca na API do TMDB informações complementares para cada filme ou série: duração, número de temporadas/episódios e plataformas de streaming disponíveis no Brasil. Grava os resultados em tabelas separadas na camada SOT e, ao final do processamento total (após o último ano de séries), aciona o Glue AGG.

## Por que existe

A API de discover do TMDB retorna metadados básicos (título, nota, gênero). Informações como duração de filmes, número de temporadas de séries e onde assistir no Brasil requerem endpoints específicos por ID. Este job faz esse enriquecimento de forma eficiente em paralelo.

## Como funciona

1. Lê os argumentos do job (media_type, year, end_year, databases, nomes dos buckets e jobs)
2. Busca a chave da API TMDB no Secrets Manager
3. Consulta o Athena para obter a lista de IDs únicos da tabela `discover` para o ano especificado (deduplicados e filtrados de IDs inválidos)
4. Para cada ID, faz duas chamadas paralelas à API TMDB (via `ThreadPoolExecutor`):
   - `/movie/{id}` ou `/tv/{id}` → retorna `runtime` (filmes) ou `number_of_seasons` + `number_of_episodes` (séries)
   - `/movie/{id}/watch/providers` ou `/tv/{id}/watch/providers` → retorna plataformas de streaming no Brasil
5. Escreve os resultados como Parquet na SOT:
   - Tabela `tb_details_{movie|tv}_tmdb`
   - Tabela `tb_watch_providers_{movie|tv}_tmdb`
6. Aciona o Glue Data Quality para cada tabela gravada
7. **Somente na última execução** (quando `media_type="tv"` e `year == end_year`): aciona o Glue AGG para unificação final

Chamadas à API usam retry com backoff exponencial e jitter para lidar com rate limits do TMDB.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `MEDIA_TYPE`, `YEAR`, `END_YEAR`, `DATABASE`, `DATABASE_UNIFIED`, nomes dos buckets e jobs |
| **Leitura** | Athena (IDs da tabela discover na SOT), Secrets Manager (chave API), API TMDB |
| **Escrita** | S3 SOT — tabelas `tb_details_*` e `tb_watch_providers_*` como Parquet + Glue Catalog |
| **Aciona** | Glue Data Quality (por tabela gravada) + Glue AGG (apenas na última execução de séries) |

## Lógica de acionamento do AGG

O Glue AGG só pode rodar após todos os detalhes de filmes e séries de todos os anos estarem prontos. O critério é: `media_type == "tv"` e `year == end_year`. Isso garante que o AGG seja acionado apenas uma vez, após o último job de detalhes de séries do ano mais recente.

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job |
| `get_tmdb_api_key(secret_arn)` | Busca a chave da API no Secrets Manager |
| `fetch_ids_from_sot(media_type, year, database, s3_bucket_temp)` | Consulta Athena para listar IDs únicos do discover |
| `_tmdb_get(url, api_key)` | GET com retry/backoff para lidar com rate limits |
| `collect_and_write_details(ids, media_type, api_key, bucket, database)` | Faz chamadas paralelas e grava tabela de detalhes |
| `collect_and_write_watch_providers(ids, media_type, api_key, bucket, database)` | Faz chamadas paralelas e grava tabela de watch providers |
| `trigger_data_quality(...)` | Aciona o job de qualidade de dados |
| `trigger_agg(...)` | Aciona o Glue AGG na última execução |

## Tecnologias

- **requests** + **ThreadPoolExecutor** — chamadas paralelas à API com controle de concorrência
- **awswrangler** — consultas Athena e escrita Parquet
- **boto3** — Secrets Manager e acionamento de jobs Glue
