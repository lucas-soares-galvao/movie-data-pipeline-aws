# glue_details — Enriquecedor de Detalhes

## O que é

O Glue Details é o terceiro estágio do pipeline de dados. Acionado pelo Glue ETL após cada tabela `discover` ser processada, ele busca na API do TMDB informações complementares para cada filme ou série: duração, número de temporadas/episódios, plataformas de streaming disponíveis no Brasil, elenco (top 5 atores), diretor, roteiristas, compositor da trilha sonora, produtor(es), diretor de fotografia, montador(a), país de origem (filmes), países de produção, keywords temáticas, classificação indicativa BR, trailer, coleção/franquia, produtoras, status, tagline, IMDB ID, títulos recomendados, títulos similares e títulos alternativos/regionais. Também traduz sinopses e keywords do inglês para o português (via Google Translate). Grava os resultados em tabelas separadas na camada SOT e, ao final do processamento total (após o último ano de séries), aciona o Glue AGG.

## Por que existe

A API de discover do TMDB retorna metadados básicos (título, nota, gênero). Informações como duração de filmes, número de temporadas de séries, elenco, diretor, produtor, diretor de fotografia, montador, keywords temáticas, classificação indicativa, títulos recomendados/similares/alternativos e onde assistir no Brasil requerem endpoints específicos por ID. Este job faz esse enriquecimento de forma eficiente em paralelo, usando o parâmetro `append_to_response` para obter credits, keywords, release_dates/content_ratings, videos, external_ids, recommendations, similar e alternative_titles na mesma chamada de API (sem custo adicional de rate limit).

## Como funciona

1. Lê os argumentos do job (media_type, year, end_year, databases, nomes dos buckets e jobs)
2. Busca a chave da API TMDB no Secrets Manager (cofre de senhas da AWS)
3. Consulta o Athena para obter a lista de todos os IDs únicos da tabela `discover` para o ano especificado
4. **Delta de detalhes (refresh mensal):** em vez de buscar detalhes de todos os IDs toda vez (o que custaria muitas chamadas à API), o job calcula o *delta* — ou seja, apenas os IDs que ainda não foram processados no mês atual. Para isso, consulta a tabela `tb_details_*` em **todas as partições `year`** e exclui IDs já processados no mês atual. Isso evita que um ID cujo `release_date` pertence a um `year` diferente do `year` do discover seja tratado como novo por um job concorrente. Somente os IDs ausentes ou de meses anteriores são buscados na API
5. Para cada ID novo, chama `/movie/{id}` ou `/tv/{id}` (via `ThreadPoolExecutor`) e grava em `tb_tmdb_details_{movie|tv}_{env}`
6. **Tradução de sinopses:** para títulos com `original_language='en'`, traduz a sinopse (overview) do inglês para português via `deep_translator.GoogleTranslator`, gravando o resultado na coluna `overview_pt`. A tradução é feita em paralelo com `ThreadPoolExecutor` (10 workers). Para outros idiomas, `overview_pt` fica nulo
6b. **Tradução de keywords:** traduz as keywords temáticas (sempre em inglês na TMDB) para português via Google Translate, gravando na coluna `keywords_pt`. Traduz todos os registros com keywords não-nulas, independente do idioma original
7. **Watch providers (refresh mensal):** mesma lógica de delta — consulta a tabela `tb_watch_providers_*` e seleciona apenas IDs *stale* (desatualizados): sem registro, com data nula ou atualizados antes do mês atual
7. Para cada ID stale, chama `/movie/{id}/watch/providers` ou `/tv/{id}/watch/providers` e grava em `tb_tmdb_watch_providers_{movie|tv}_{env}`
8. Aciona o Glue Data Quality para cada tabela gravada
9. **Ao final do ciclo de cada `media_type`** (quando `year == end_year`): executa `repair_discover_duplicates`, `repair_watch_providers_duplicates` e `repair_details_duplicates` para eliminar IDs duplicados na partição do ano corrente. Cada repair lê o Parquet diretamente via S3, aplica `drop_duplicates` e grava de volta apenas se houver mudanças. Movie e TV reparando suas próprias tabelas em runs separados
10. **Somente na última execução geral** (quando `media_type="tv"` e `year == end_year`): aciona o Glue AGG para unificação final

Chamadas à API usam **retry com backoff exponencial e jitter** para lidar com rate limits do TMDB — se a API retornar erro 429 (muitas requisições), o código espera um tempo crescente entre tentativas (ex: 1s, 2s, 4s…) com uma variação aleatória (jitter) para evitar que múltiplos workers tentem ao mesmo tempo.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `MEDIA_TYPE`, `YEAR`, `END_YEAR`, `DATABASE`, nomes dos buckets e jobs |
| **Leitura** | Athena (IDs da tabela discover na SOT), Secrets Manager (chave API), API TMDB |
| **Escrita** | S3 SOT — tabelas `tb_details_*` e `tb_watch_providers_*` como Parquet + Glue Catalog |
| **Aciona** | Glue Data Quality (por tabela gravada) + Glue AGG (apenas na última execução de séries) |

## Lógica de acionamento do AGG

O Glue AGG só pode rodar após todos os detalhes de filmes e séries de todos os anos estarem prontos. O critério é: `media_type == "tv"` e `year == end_year`. Isso garante que o AGG seja acionado apenas uma vez, após o último job de detalhes de séries do ano mais recente.

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job |
| `fetch_ids_from_sot(...)` | Consulta Athena para listar todos os IDs únicos do discover |
| `fetch_existing_ids_from_details(...)` | Retorna IDs já processados no mês atual em **qualquer partição `year`** (sem filtro de ano) — usados para calcular o delta e evitar reprocessamento por jobs concorrentes |
| `fetch_ids_stale_watch_providers(...)` | Retorna IDs sem watch providers ou atualizados antes do mês atual |
| `_extrair_elenco(creditos, limite)` | Top N atores por billing order, comma-separated |
| `_extrair_diretor(creditos)` | Diretor(es) do filme/série (job='Director' no crew) |
| `_extrair_roteiristas(creditos)` | Roteiristas (job='Screenplay'/'Writer' no crew), deduplicados |
| `_extrair_compositor(creditos)` | Compositor(es) da trilha sonora (job='Original Music Composer') |
| `_extrair_keywords(dados)` | Keywords temáticas comma-separated |
| `_extrair_certificacao_br_movie(release_dates)` | Classificação indicativa BR para filmes |
| `_extrair_certificacao_br_tv(content_ratings)` | Classificação indicativa BR para séries |
| `_extrair_trailer_url(videos)` | Primeiro trailer oficial do YouTube |
| `_extrair_produtoras(companies)` | Nomes das produtoras comma-separated |
| `_extrair_criadores(created_by)` | Criadores de série comma-separated |
| `_extrair_networks(networks)` | Redes de TV comma-separated |
| `_extrair_spoken_languages(spoken_languages)` | Idiomas falados comma-separated |
| `_extrair_produtores(creditos, limite)` | Produtor(es) e produtores executivos, deduplicados, top N |
| `_extrair_cinematografo(creditos)` | Diretor(es) de fotografia (job='Director of Photography') |
| `_extrair_montador(creditos)` | Montador(es) (job='Editor') |
| `_extrair_paises_producao(production_countries)` | Países de produção comma-separated |
| `_extrair_titulos_recomendados(recommendations, content_type, limite)` | Top N títulos recomendados pelo TMDB |
| `_extrair_titulos_similares(similar, content_type, limite)` | Top N títulos similares pelo TMDB |
| `_extrair_titulos_alternativos(alternative_titles, content_type)` | Títulos alternativos/regionais |
| `collect_and_write_details(ids, ...)` | Faz chamadas paralelas e grava tabela de detalhes |
| `collect_and_write_watch_providers(ids, ...)` | Faz chamadas paralelas e grava tabela de watch providers |
| `repair_discover_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id)` mantendo o registro de maior `popularity` e regrava apenas se houver mudanças |
| `repair_watch_providers_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id, provider_type, provider_id)` mantendo o `dt_atualizacao` mais recente e regrava apenas se houver mudanças |
| `repair_details_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id)` mantendo o registro com `dt_processamento` mais recente e regrava apenas se houver mudanças |

## Funções compartilhadas (`shared_utils/`)

Importadas do pacote `shared_utils`, reutilizadas por múltiplos componentes do pipeline:

| Função | Origem | Responsabilidade |
|---|---|---|
| `api_get(url, params, max_retries)` | `shared_utils.api_client` | GET com retry/backoff para lidar com rate limits de APIs |
| `get_api_secret(secret_arn, key_name)` | `shared_utils.api_client` | Busca um segredo no Secrets Manager |
| `trigger_glue_job(job_name, **arguments)` | `shared_utils.triggers` | Dispara qualquer job Glue (DQ, AGG) com argumentos dinâmicos |

## Tecnologias

- **requests** + **ThreadPoolExecutor** — chamadas paralelas à API com controle de concorrência
- **deep_translator** (GoogleTranslator) — tradução de sinopses EN→PT via Google Translate
- **awswrangler** — consultas Athena e escrita Parquet
- **boto3** — Secrets Manager e acionamento de jobs Glue
