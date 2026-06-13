# glue_details — Enriquecedor de Detalhes

## O que é

O Glue Details é o terceiro estágio do pipeline de dados. Acionado pelo Glue ETL após cada tabela `discover` ser processada, ele busca na API do TMDB informações complementares para cada filme ou série: duração, número de temporadas/episódios e plataformas de streaming disponíveis no Brasil. Grava os resultados em tabelas separadas na camada SOT e, ao final do processamento total (após o último ano de séries), aciona o Glue AGG.

## Por que existe

A API de discover do TMDB retorna metadados básicos (título, nota, gênero). Informações como duração de filmes, número de temporadas de séries e onde assistir no Brasil requerem endpoints específicos por ID. Este job faz esse enriquecimento de forma eficiente em paralelo.

## Como funciona

1. Lê os argumentos do job (media_type, year, end_year, databases, nomes dos buckets e jobs)
2. Busca a chave da API TMDB no Secrets Manager (cofre de senhas da AWS)
3. Consulta o Athena para obter a lista de todos os IDs únicos da tabela `discover` para o ano especificado
4. **Delta de detalhes (refresh mensal):** em vez de buscar detalhes de todos os IDs toda vez (o que custaria muitas chamadas à API), o job calcula o *delta* — ou seja, apenas os IDs que ainda não foram processados no mês atual. Para isso, consulta a tabela `tb_details_*` em **todas as partições `year`** e exclui IDs já processados no mês atual. Isso evita que um ID cujo `release_date` pertence a um `year` diferente do `year` do discover seja tratado como novo por um job concorrente. Somente os IDs ausentes ou de meses anteriores são buscados na API
5. Para cada ID novo, chama `/movie/{id}` ou `/tv/{id}` (via `ThreadPoolExecutor`) e grava em `tb_details_{movie|tv}_tmdb`
6. **Watch providers (refresh mensal):** mesma lógica de delta — consulta a tabela `tb_watch_providers_*` e seleciona apenas IDs *stale* (desatualizados): sem registro, com data nula ou atualizados antes do mês atual
7. Para cada ID stale, chama `/movie/{id}/watch/providers` ou `/tv/{id}/watch/providers` e grava em `tb_watch_providers_{movie|tv}_tmdb`
8. Aciona o Glue Data Quality para cada tabela gravada
9. **Ao final do ciclo de cada `media_type`** (quando `year == end_year`): executa `repair_discover_duplicates`, `repair_watch_providers_duplicates` e `repair_details_duplicates` para eliminar IDs duplicados na partição do ano corrente. Cada repair lê o Parquet diretamente via S3, aplica `drop_duplicates` e grava de volta apenas se houver mudanças. Movie e TV reparando suas próprias tabelas em runs separados
10. **Somente na última execução geral** (quando `media_type="tv"` e `year == end_year`): aciona o Glue AGG para unificação final

Chamadas à API usam **retry com backoff exponencial e jitter** para lidar com rate limits do TMDB — se a API retornar erro 429 (muitas requisições), o código espera um tempo crescente entre tentativas (ex: 1s, 2s, 4s…) com uma variação aleatória (jitter) para evitar que múltiplos workers tentem ao mesmo tempo.

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
| `fetch_ids_from_sot(...)` | Consulta Athena para listar todos os IDs únicos do discover |
| `fetch_existing_ids_from_details(...)` | Retorna IDs já processados no mês atual em **qualquer partição `year`** (sem filtro de ano) — usados para calcular o delta e evitar reprocessamento por jobs concorrentes |
| `fetch_ids_stale_watch_providers(...)` | Retorna IDs sem watch providers ou atualizados antes do mês atual |
| `_tmdb_get(url, api_key)` | GET com retry/backoff para lidar com rate limits |
| `collect_and_write_details(ids, ...)` | Faz chamadas paralelas e grava tabela de detalhes |
| `collect_and_write_watch_providers(ids, ...)` | Faz chamadas paralelas e grava tabela de watch providers |
| `repair_discover_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id)` mantendo o registro de maior `popularity` e regrava apenas se houver mudanças |
| `repair_watch_providers_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id, provider_type, provider_id)` mantendo o `dt_atualizacao` mais recente e regrava apenas se houver mudanças |
| `repair_details_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id)` mantendo o registro com `dt_processamento` mais recente e regrava apenas se houver mudanças |
| `trigger_data_quality(...)` | Aciona o job de qualidade de dados |
| `trigger_agg(...)` | Aciona o Glue AGG na última execução |

## Tecnologias

- **requests** + **ThreadPoolExecutor** — chamadas paralelas à API com controle de concorrência
- **awswrangler** — consultas Athena e escrita Parquet
- **boto3** — Secrets Manager e acionamento de jobs Glue
