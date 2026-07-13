# glue_details — Enriquecedor de Detalhes

## O que é

O Glue Details é o terceiro estágio do pipeline de dados. Acionado pelo Glue ETL após cada tabela `discover` ser processada, ele busca na API do TMDB informações complementares para cada filme ou série: duração, número de temporadas/episódios, plataformas de streaming disponíveis no Brasil, elenco (top 5 atores), diretor, roteiristas, compositor da trilha sonora, produtor(es), diretor de fotografia, montador(a), país de origem (filmes), países de produção, keywords temáticas, classificação indicativa BR, trailer, coleção/franquia, produtoras, status, tagline, IMDB ID, títulos recomendados, títulos similares e títulos alternativos/regionais. Também obtém traduções pt-BR de sinopses e taglines diretamente do TMDB (via `append_to_response=translations`) e, quando não disponíveis, traduz para o português via **AWS Translate** (serviço usado por padrão neste caminho automático via EventBridge — ver `TRANSLATE_PROVIDER`) ou Google Translate. Keywords são sempre traduzidas (o TMDB não as localiza), pelo mesmo serviço. Grava os resultados em tabelas separadas na camada SOT e, ao final do processamento total (após o último ano de séries), aciona o Glue AGG.

## Por que existe

A API de discover do TMDB retorna metadados básicos (título, nota, gênero). Informações como duração de filmes, número de temporadas de séries, elenco, diretor, produtor, diretor de fotografia, montador, keywords temáticas, classificação indicativa, títulos recomendados/similares/alternativos e onde assistir no Brasil requerem endpoints específicos por ID. Este job faz esse enriquecimento de forma eficiente em paralelo, usando o parâmetro `append_to_response` para obter credits, keywords, release_dates/content_ratings, videos, external_ids, recommendations, similar, alternative_titles e translations na mesma chamada de API (sem custo adicional de rate limit).

## Como funciona

1. Lê os argumentos do job (media_type, year, end_year, databases, nomes dos buckets e jobs)
2. Busca a chave da API TMDB no Secrets Manager (cofre de senhas da AWS)
3. Consulta o Athena para obter a lista de todos os IDs únicos da tabela `discover` para o ano especificado
4. **Delta de detalhes (refresh mensal):** em vez de buscar detalhes de todos os IDs toda vez (o que custaria muitas chamadas à API), o job calcula o *delta* — ou seja, apenas os IDs que ainda não foram processados no mês atual. Para isso, consulta a tabela `tb_details_*` em **todas as partições `year`** e exclui IDs já processados no mês atual. Isso evita que um ID cujo `release_date` pertence a um `year` diferente do `year` do discover seja tratado como novo por um job concorrente. Somente os IDs ausentes ou de meses anteriores são buscados na API. Opcionalmente, o argumento `FORCE_REFETCH=true` ignora todo esse cálculo de delta e rebusca todos os IDs do discover na API — útil para forçar um refresh completo fora do ciclo mensal
5. Para cada ID novo, chama `/movie/{id}` ou `/tv/{id}` (via `ThreadPoolExecutor`) e grava em `tb_tmdb_details_{movie|tv}_{env}`. Registros sem `release_date`/`first_air_date` ficam sem `year` e são descartados antes da gravação — se **todos** os registros do lote ficarem sem `year`, nada é gravado neste run (evita erro de partição vazia no S3). Antes de traduzir, lê uma única vez (por partição `year` afetada) os registros já existentes no S3: os que **não** fazem parte do delta atual são preservados para o merge final de escrita; os que **fazem** parte do delta alimentam o cache de tradução do passo 6 (mesma leitura reaproveitada para as duas finalidades, sem consultar o S3 duas vezes)
6. **Tradução de sinopses (TMDB pt-BR → cache do S3 → Google/AWS Translate):** primeiro verifica se o TMDB já possui tradução pt-BR (extraída do `append_to_response=translations`). Caso exista, usa diretamente. Caso contrário, verifica se `overview_en` é idêntico ao registro stale lido do S3 durante o cálculo do delta (ver passo 4) — se for, reaproveita `overview_pt` já persistido sem chamar a API de tradução de novo. Só quando não há tradução nativa nem cache aproveitável, para títulos com `original_language` diferente de `pt` e `overview_en` não-vazio, traduz via `resolve_translate_fn(TRANSLATE_PROVIDER)` — `"aws"` (default deste job, via `AWS Translate`/boto3) ou `"google"` (`deep_translator.GoogleTranslator`, `source="auto"`, com retry/backoff em `translate_text`, já que o endpoint não-oficial falha esporadicamente sob alto volume). Grava na coluna `overview_pt`. Para títulos já em `pt` ou com `overview_en` vazio, `overview_pt` fica nulo
6b. **Tradução de keywords:** mesma prioridade de cache do item 6 (reaproveita `keywords_pt` existente quando `keywords` não mudou desde o último processamento) antes de traduzir as keywords temáticas (sempre em inglês na TMDB para idiomas diferentes de `pt`, não suportam localização) para português pelo mesmo serviço do item 6, gravando na coluna `keywords_pt`. Traduz registros com keywords não-nulas e `original_language` diferente de `pt` — pula conteúdo já em português para não gastar chamadas de tradução à toa
6c. **Tradução de tagline (TMDB pt-BR → cache do S3 → Google/AWS Translate):** primeiro verifica se o TMDB já possui tradução pt-BR da tagline. Caso exista, usa diretamente. Caso contrário, reaproveita `tagline_pt` existente quando `tagline` não mudou desde o último processamento (mesma lógica de cache do item 6). Só então traduz pelo mesmo serviço do item 6 — o idioma de origem é detectado automaticamente, o que importa aqui porque a tagline é traduzida para qualquer `original_language` diferente de `pt`. Grava na coluna `tagline_pt`
6d. **Países de produção:** extrai os códigos ISO 3166-1 dos países de produção (`production_countries_iso`) para lookup na tabela de referência `tb_configuration_countries` no Glue AGG (substituindo o antigo Google Translate)
6e2. **Idiomas falados:** extrai os códigos ISO 639-1 dos idiomas falados (`spoken_languages_iso`) para lookup na tabela de referência `tb_configuration_languages` no Glue AGG, resolvendo nomes em português
6e. **Coleções em pt-BR:** para filmes com coleção/franquia, busca o nome em português via `/collection/{id}?language=pt-BR` na API do TMDB. Chamadas deduplicadas por collection_id (1 chamada para toda a coleção, ex: Marvel = 1 chamada para 30+ filmes). Grava na coluna `collection_name_pt`
7. **Watch providers (refresh mensal):** mesma lógica de delta — consulta a tabela `tb_watch_providers_*` e seleciona apenas IDs *stale* (desatualizados): sem registro, com data nula ou atualizados antes do mês atual
7. Para cada ID stale, chama `/movie/{id}/watch/providers` ou `/tv/{id}/watch/providers` e grava em `tb_tmdb_watch_providers_{movie|tv}_{env}`
8. Aciona o Glue Data Quality para cada tabela gravada
9. **Ao final do ciclo de cada `media_type`** (quando `year == end_year`): executa `repair_discover_duplicates`, `repair_watch_providers_duplicates` e `repair_details_duplicates` para eliminar IDs duplicados na partição do ano corrente. Cada repair lê o Parquet diretamente via S3, aplica `drop_duplicates` e grava de volta apenas se houver mudanças. Movie e TV reparando suas próprias tabelas em runs separados
10. **Somente na última execução geral** (quando `media_type="tv"` e `year == end_year`): aciona o Glue AGG para unificação final

Chamadas à API usam **retry com backoff exponencial e jitter** para lidar com rate limits do TMDB — se a API retornar erro 429 (muitas requisições), o código espera um tempo crescente entre tentativas (ex: 1s, 2s, 4s…) com uma variação aleatória (jitter) para evitar que múltiplos workers tentem ao mesmo tempo.

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `MEDIA_TYPE`, `YEAR`, `END_YEAR`, `DATABASE`, nomes dos buckets e jobs, `FORCE_REFETCH` (opcional, default `false`), `TRANSLATE_PROVIDER` (opcional, default `"aws"` — serviço de tradução; ver `resolve_translate_fn` em `shared_utils.traducao`) |
| **Leitura** | Athena (IDs da tabela discover na SOT), Secrets Manager (chave API), API TMDB |
| **Escrita** | S3 SOT — tabelas `tb_details_*` e `tb_watch_providers_*` como Parquet + Glue Catalog |
| **Aciona** | Glue Data Quality (por tabela gravada) + Glue AGG (apenas na última execução de séries) |

## Lógica de acionamento do AGG

O Glue AGG só pode rodar após todos os detalhes de filmes e séries de todos os anos estarem prontos. O critério é: `media_type == "tv"` e `year == end_year`. Isso garante que o AGG seja acionado apenas uma vez, após o último job de detalhes de séries do ano mais recente.

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `get_parameters_glue()` | Lê e valida os argumentos de execução do job (inclui leitura manual de `FORCE_REFETCH` e `TRANSLATE_PROVIDER`, ambos opcionais) |
| `fetch_ids_from_sot(...)` | Consulta Athena para listar todos os IDs únicos do discover |
| `fetch_existing_ids_from_details(...)` | Retorna IDs já processados no mês atual em **qualquer partição `year`** (sem filtro de ano) — usados para calcular o delta e evitar reprocessamento por jobs concorrentes |
| `fetch_ids_stale_watch_providers(...)` | Retorna IDs sem watch providers ou atualizados antes do mês atual |
| `fetch_tmdb_details(api_key, content_type, item_id)` | Chama `/movie/{id}` ou `/tv/{id}` na API do TMDB e retorna o JSON bruto |
| `fetch_tmdb_watch_providers(api_key, content_type, item_id)` | Chama `/movie/{id}/watch/providers` ou `/tv/{id}/watch/providers` e retorna a seção `BR` do payload |
| `_parse_watch_providers(br_data, item_id, year)` | Converte a seção `BR` de watch providers em registros (um por provedor/tipo `flatrate`/`rent`/`buy`) |
| `_run_parallel(func, items, max_workers)` | Helper genérico de execução paralela via `ThreadPoolExecutor`, usado por `collect_and_write_details`/`collect_and_write_watch_providers` e por `_fetch_collections_pt_br` |
| `_extract_names_from_list(items, *, filter_field, filter_value)` | Helper compartilhado por várias `_extract_*` que filtram uma lista de dicts por campo/valor e retornam nomes comma-separated |
| `_common_fields`, `_movie_fields`, `_tv_fields`, `_parse_detail` | Montam o registro final de detalhes a partir do JSON da API, combinando campos comuns e específicos de filme/série |
| `_extract_cast(credits, limit)` | Top N atores por billing order, comma-separated |
| `_extract_director(credits)` | Diretor(es) do filme/série (job='Director' no crew) |
| `_extract_writers(credits)` | Roteiristas (job='Screenplay'/'Writer' no crew), deduplicados |
| `_extract_composer(credits)` | Compositor(es) da trilha sonora (job='Original Music Composer') |
| `_extract_keywords(keywords_data)` | Keywords temáticas comma-separated |
| `_extract_certification_br_movie(release_dates)` | Classificação indicativa BR para filmes |
| `_extract_certification_br_tv(content_ratings)` | Classificação indicativa BR para séries |
| `_extract_trailer_url(videos)` | Primeiro trailer oficial do YouTube |
| `_extract_production_companies(companies)` | Nomes das produtoras comma-separated |
| `_extract_creators(created_by)` | Criadores de série comma-separated |
| `_extract_networks(networks)` | Redes de TV comma-separated |
| `_extract_spoken_languages(spoken_languages)` | Idiomas falados comma-separated (prioriza `name` nativo sobre `english_name`) |
| `_extract_spoken_languages_iso(spoken_languages)` | Códigos ISO 639-1 dos idiomas falados como array (para lookup no AGG) |
| `_extract_producers(credits, limit)` | Produtor(es) e produtores executivos, deduplicados, top N |
| `_extract_cinematographer(credits)` | Diretor(es) de fotografia (job='Director of Photography') |
| `_extract_editor(credits)` | Montador(es) (job='Editor') |
| `_extract_production_countries(production_countries)` | Países de produção comma-separated |
| `_extract_recommended_titles(recommendations, content_type, limit)` | Top N títulos recomendados pelo TMDB |
| `_extract_recommended_ids(recommendations, limit)` | Top N IDs recomendados pelo TMDB (para cross-reference com discover pt-BR no glue_agg) |
| `_extract_similar_titles(similar, content_type, limit)` | Top N títulos similares pelo TMDB |
| `_extract_similar_ids(similar, limit)` | Top N IDs similares pelo TMDB (para cross-reference com discover pt-BR no glue_agg) |
| `_extract_alternative_titles(alternative_titles, content_type)` | Títulos alternativos/regionais |
| `_extract_pt_br_translation(translations)` | Extrai overview e tagline em pt-BR do array de translations do TMDB |
| `_extract_production_countries_iso(production_countries)` | Códigos ISO 3166-1 dos países de produção como array |
| `_add_translations_pt(df, translate_fn=None, previous_df=None)` | Prioriza overview pt-BR do TMDB; em seguida reaproveita `overview_pt` existente via `reuse_existing_translation` (`shared_utils.traducao`) quando `overview_en` não mudou; só então traduz via `shared_utils.traducao.translate_pending_column` usando `translate_fn` (default `translate_text_aws` quando não informado; `collect_and_write_details` injeta o serviço resolvido de `TRANSLATE_PROVIDER`). Elegibilidade (`original_language != 'pt'` e `overview_en` não-vazio) vem de `shared_utils.traducao.eligible_overview_pt` |
| `_add_translations_keywords_pt(df, translate_fn=None, previous_df=None)` | Reaproveita `keywords_pt` existente via `reuse_existing_translation` quando `keywords` não mudou; caso contrário traduz para PT (TMDB não localiza keywords) via `shared_utils.traducao.translate_pending_column` usando `translate_fn`. Elegibilidade (`original_language != 'pt'` e `keywords` não-vazio) vem de `shared_utils.traducao.eligible_keywords_pt` |
| `_add_translations_tagline_pt(df, translate_fn=None, previous_df=None)` | Prioriza tagline pt-BR do TMDB; em seguida reaproveita `tagline_pt` existente via `reuse_existing_translation` quando `tagline` não mudou; só então traduz via `shared_utils.traducao.translate_pending_column` usando `translate_fn` (idioma de origem detectado automaticamente). Elegibilidade (`original_language != 'pt'` e `tagline` não-vazio) vem de `shared_utils.traducao.eligible_tagline_pt` |
| `_fetch_collections_pt_br(api_key, collection_ids)` | Busca nomes de coleções em pt-BR na API do TMDB via chamadas paralelas |
| `_add_collection_name_pt(df, api_key)` | Adiciona coluna `collection_name_pt` ao DataFrame de detalhes de filmes |
| `collect_and_write_details(ids, ..., translate_provider="aws")` | Faz chamadas paralelas e grava tabela de detalhes. Antes de traduzir, lê o S3 uma única vez por partição `year` afetada, separando os registros existentes em `df_existing_delta` (ids do delta atual, usados como cache de tradução) e `df_existing_keep` (ids fora do delta, preservados no merge final) — a mesma leitura alimenta as duas finalidades. Resolve o `translate_fn` (via `resolve_translate_fn(translate_provider, translate_text, translate_text_aws)`, passando as referências locais para preservar os mocks de teste) uma vez por execução e passa, junto com `df_existing_delta`, às 3 `_add_translations_*` |
| `collect_and_write_watch_providers(ids, ...)` | Faz chamadas paralelas e grava tabela de watch providers |
| `_repair_partition_duplicates(...)` | Implementação compartilhada pelos três `repair_*` abaixo: lê a partição `year` via S3, aplica `drop_duplicates` com a chave/critério de desempate recebidos como parâmetro e regrava apenas se houver mudanças |
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
| `translate_text(text, context="")` | `shared_utils.traducao_google` (reexportada em `shared_utils.traducao`) | Traduz texto para PT via Google Translate com detecção automática do idioma de origem; retorna o texto original em caso de falha |
| `translate_text_aws(text, region="us-east-1")` | `shared_utils.traducao_aws` (reexportada em `shared_utils.traducao`) | Traduz texto para PT via AWS Translate (boto3); retorna o texto original em caso de falha |
| `resolve_translate_fn(provider, translate_google=translate_text, translate_aws=translate_text_aws)` | `shared_utils.traducao` | Resolve `TRANSLATE_PROVIDER` (`"google"` ou `"aws"`) para a função a usar — este job usa `"aws"` por padrão. Levanta `ValueError` para qualquer outro valor |
| `translate_in_parallel(values, translate_fn, max_workers)` | `shared_utils.traducao` | Aplica `translate_fn` a cada valor em paralelo via `ThreadPoolExecutor`; usada por `translate_pending_column` |
| `translate_pending_column(df, source_column, target_column, eligible_mask, translate_fn, max_workers)` | `shared_utils.traducao` | Orquestra a tradução coluna a coluna: pula registros já traduzidos (`target_column` preenchida e diferente de `source_column`), retenta os que ficaram iguais à fonte (fallback de falha anterior), grava o resultado e devolve a contagem de sucesso. Compartilhada com `scripts/backfill_traducao.py` para evitar que as duas cópias divirjam |
| `reuse_existing_translation(df, previous_df, source_column, target_column, key_column="id")` | `shared_utils.traducao` | Pré-preenche `target_column` do `df` novo com o valor já persistido (`previous_df`) quando `source_column` não mudou para o mesmo `key_column`. Não sobrescreve valor já preenchido (prioridade da tradução nativa do TMDB); registros novos sem histórico ou schema antigo sem a coluna não são afetados. O reaproveitamento é reconhecido pela checagem "já traduzido" já existente em `translate_pending_column`, sem duplicar lógica. Compartilhada com `glue_etl` (que usa `key_column="iso_3166_1"`/`"iso_639_1"` para a tabela `configuration`) |
| `eligible_overview_pt(df)` / `eligible_tagline_pt(df)` / `eligible_keywords_pt(df)` | `shared_utils.traducao` | Masks de candidatos à tradução por campo, compartilhadas com `scripts/backfill_traducao.py` para evitar que as duas cópias divirjam |
| `get_resolved_option(args)` | `shared_utils.glue_helpers` | Wrapper de `getResolvedOptions` — converte lista de nomes de argumentos em dicionário nome→valor |
| `configure_glue_logging()` | `shared_utils.glue_helpers` | Configura o logging padrão dos jobs Glue (stdout, nível INFO, formato com timestamp) |

## Tecnologias

- **requests** + **ThreadPoolExecutor** — chamadas paralelas à API com controle de concorrência
- **AWS Translate** (via boto3) — serviço de tradução default deste job (`TRANSLATE_PROVIDER="aws"`, caminho automático via EventBridge) para sinopses, keywords e taglines quando a tradução pt-BR não existe no TMDB; sem custo de API key/secret (usa a role IAM do job)
- **deep_translator** (GoogleTranslator, `source="auto"`) — alternativa via `TRANSLATE_PROVIDER="google"`, com detecção automática do idioma de origem
- **awswrangler** — consultas Athena e escrita Parquet
- **boto3** — Secrets Manager, AWS Translate e acionamento de jobs Glue
