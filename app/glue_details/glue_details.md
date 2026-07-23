# glue_details — Enriquecedor de Detalhes

## O que é

O Glue Details é o terceiro estágio do pipeline de dados. Acionado pelo Glue ETL após cada tabela `discover` ser processada, ele busca na API do TMDB informações complementares para cada filme ou série: duração, número de temporadas/episódios, plataformas de streaming disponíveis no Brasil, elenco (top 5 atores), diretor, roteiristas, compositor da trilha sonora, produtor(es), diretor de fotografia, montador(a), país de origem (filmes), países de produção, keywords temáticas, classificação indicativa BR, trailer, coleção/franquia, produtoras, status, tagline, IMDB ID, títulos recomendados, títulos similares e títulos alternativos/regionais. Também obtém traduções pt-BR de sinopses e taglines diretamente do TMDB (via `append_to_response=translations`) e, quando não disponíveis, traduz para o português via **Google Translate** (serviço usado por padrão neste caminho automático via EventBridge — ver `TRANSLATE_PROVIDER`) ou AWS Translate. Qualquer que seja o escolhido, o outro serviço é usado automaticamente como fallback caso o primário falhe (ver `resolve_translate_fn`) — AWS Translate como fallback é limitado por um orçamento de caracteres por execução, já que é pago por caractere. Keywords são sempre traduzidas (o TMDB não as localiza), pelo mesmo serviço. Antes de qualquer tradução, detecta o idioma do texto fonte (`overview_en`/`tagline`/`keywords`) via `langdetect` (local, com fallback AWS Comprehend), gravando `<campo>_detected_language_en`; quando a fonte já é detectada como `pt`, copia direto para `<campo>_pt` sem chamar Google/AWS (evita retradução infinita de texto que já está correto). O idioma do **resultado** também é detectado e gravado em `<campo>_detected_language_pt` — é esse idioma (não uma comparação de string com a fonte) que decide se o campo ainda precisa de tradução, o que evita tanto retraduzir o que já está correto quanto deixar uma mistradução silenciosa marcada como concluída para sempre. `<campo>_translation_attempts` conta quantas vezes uma linha foi reenviada ao tradutor, para não retentar para sempre conteúdo genuinamente não traduzível (nomes próprios, termos curtos). Grava os resultados em tabelas separadas na camada SOT e, ao final do processamento total (após o último ano de séries), aciona o Glue AGG.

## Por que existe

A API de discover do TMDB retorna metadados básicos (título, nota, gênero). Informações como duração de filmes, número de temporadas de séries, elenco, diretor, produtor, diretor de fotografia, montador, keywords temáticas, classificação indicativa, títulos recomendados/similares/alternativos e onde assistir no Brasil requerem endpoints específicos por ID. Este job faz esse enriquecimento de forma eficiente em paralelo, usando o parâmetro `append_to_response` para obter credits, keywords, release_dates/content_ratings, videos, external_ids, recommendations, similar, alternative_titles e translations na mesma chamada de API (sem custo adicional de rate limit).

## Como funciona

1. Lê os argumentos do job (media_type, year, end_year, databases, nomes dos buckets e jobs)
2. Busca a chave da API TMDB no Secrets Manager (cofre de senhas da AWS)
3. Consulta o Athena para obter a lista de todos os IDs únicos da tabela `discover` para o ano especificado
4. **Delta de detalhes (refresh mensal):** em vez de buscar detalhes de todos os IDs toda vez (o que custaria muitas chamadas à API), o job calcula o *delta* — ou seja, apenas os IDs que ainda não foram processados no mês atual. Para isso, consulta a tabela `tb_details_*` em **todas as partições `year`** e exclui IDs já processados no mês atual. Isso evita que um ID cujo `release_date` pertence a um `year` diferente do `year` do discover seja tratado como novo por um job concorrente. Somente os IDs ausentes ou de meses anteriores são buscados na API. Opcionalmente, o argumento `FORCE_REFETCH=true` ignora todo esse cálculo de delta e rebusca todos os IDs do discover na API — útil para forçar um refresh completo fora do ciclo mensal
5. Para cada ID novo, chama `/movie/{id}` ou `/tv/{id}` (via `ThreadPoolExecutor`) e grava em `tb_tmdb_details_{movie|tv}_{env}`. Registros sem `release_date`/`first_air_date` ficam sem `year` e são descartados antes da gravação — se **todos** os registros do lote ficarem sem `year`, nada é gravado neste run (evita erro de partição vazia no S3). Antes de traduzir, lê uma única vez (por partição `year` afetada) os registros já existentes no S3: os que **não** fazem parte do delta atual são preservados para o merge final de escrita; os que **fazem** parte do delta alimentam o cache de tradução do passo 6 (mesma leitura reaproveitada para as duas finalidades, sem consultar o S3 duas vezes)
6. **Tradução de sinopses (TMDB pt-BR → cache do S3 → idioma detectado → cópia direta ou Google/AWS Translate):** verifica primeiro se o TMDB já possui tradução pt-BR (extraída do `append_to_response=translations`); caso exista, usa diretamente. Caso contrário, verifica se `overview_en` é idêntico ao registro stale lido do S3 durante o cálculo do delta (ver passo 4) — se for, reaproveita `overview_pt` já persistido sem chamar a API de tradução de novo. A partir daí, `resolve_pt_translation` (`shared_utils.traducao`) assume o resto do fluxo: detecta o idioma de `overview_en` (grava `overview_detected_language_en`) e do valor atual de `overview_pt` (grava `overview_detected_language_pt`), copia `overview_en` direto para `overview_pt` quando a fonte já é `"pt"` e `overview_pt` ainda está vazia (sem chamar tradução), e traduz via `resolve_translate_fn(TRANSLATE_PROVIDER)` — `"google"` (default deste job, `deep_translator.GoogleTranslator`, `source="auto"`, com retry/backoff em `translate_text`, já que o endpoint não-oficial falha esporadicamente sob alto volume) ou `"aws"` (`AWS Translate`/boto3) — todo registro com `overview_en` preenchido cujo `overview_detected_language_pt` ainda não seja `"pt"` e que não tenha esgotado `overview_translation_attempts` (teto contra retry infinito de conteúdo genuinamente não traduzível). O serviço não escolhido é usado automaticamente como fallback. `original_language` não entra em nenhum critério — é o idioma de produção original do título, não o idioma do texto retornado pela API, e não garante que `overview_en` já esteja em português (ver `shared_utils/traducao.py`). Também grava `overview_needs_translation` (booleano): `overview_en` preenchido E `overview_detected_language_pt != "pt"`, sem o teto de tentativas — ao contrário do critério de elegibilidade acima, continua `True` mesmo depois de `overview_translation_attempts` esgotar, sinalizando para consumidores (ex.: FilmBot) que o texto ainda não está confiavelmente em português
6b. **Tradução de keywords (cache do S3 → idioma detectado → cópia direta ou Google/AWS Translate):** mesmo fluxo do item 6 via `resolve_pt_translation`, aplicado a `keywords` (grava `keywords_detected_language_en`/`keywords_detected_language_pt`/`keywords_translation_attempts`/`keywords_needs_translation`), sem tradução nativa do TMDB (o TMDB não localiza keywords por idioma — nem mesmo para títulos com `original_language == 'pt'`), gravando na coluna `keywords_pt`
6c. **Tradução de tagline (TMDB pt-BR → cache do S3 → idioma detectado → cópia direta ou Google/AWS Translate):** mesmo fluxo do item 6 (incluindo a prioridade de tradução nativa do TMDB), aplicado a `tagline` (grava `tagline_detected_language_en`/`tagline_detected_language_pt`/`tagline_translation_attempts`/`tagline_needs_translation`), gravando na coluna `tagline_pt`
6d. **Países de produção:** extrai os códigos ISO 3166-1 dos países de produção (`production_countries_iso`) para lookup na tabela de referência `tb_configuration_countries` no Glue AGG (substituindo o antigo Google Translate)
6e2. **Idiomas falados:** extrai os códigos ISO 639-1 dos idiomas falados (`spoken_languages_iso`) para lookup na tabela de referência `tb_configuration_languages` no Glue AGG, resolvendo nomes em português
6e. **Coleções em pt-BR:** para filmes com coleção/franquia, busca o nome em português via `/collection/{id}?language=pt-BR` na API do TMDB. Chamadas deduplicadas por collection_id (1 chamada para toda a coleção, ex: Marvel = 1 chamada para 30+ filmes). Grava na coluna `collection_name_pt`
7. **Watch providers (refresh mensal):** mesma lógica de delta — consulta a tabela `tb_watch_providers_*` e seleciona apenas IDs *stale* (desatualizados): sem registro, com data nula ou atualizados antes do mês atual
7. Para cada ID stale, chama `/movie/{id}/watch/providers` ou `/tv/{id}/watch/providers` e grava em `tb_tmdb_watch_providers_{movie|tv}_{env}`
8. Aciona o Glue Data Quality para cada tabela gravada
9. **Ao final do ciclo de cada `media_type`** (quando `year == end_year`): executa `repair_discover_duplicates`, `repair_watch_providers_duplicates` e `repair_details_duplicates` para eliminar IDs duplicados na partição do ano corrente. Cada repair lê o Parquet diretamente via S3, aplica `drop_duplicates` e grava de volta apenas se houver mudanças. Movie e TV reparando suas próprias tabelas em runs separados
10. **Somente na última execução geral** (quando `media_type="tv"` e `year == end_year`): aciona o Glue AGG para unificação final

Chamadas à API usam **retry com backoff exponencial e jitter** para lidar com rate limits do TMDB — se a API retornar erro 429 (muitas requisições), o código espera um tempo crescente entre tentativas (ex: 1s, 2s, 4s…) com uma variação aleatória (jitter) para evitar que múltiplos workers tentem ao mesmo tempo.

### Modo changes (TMDB Changes API)

Acionado pela `lambda_api` (modo `only_changes_tables`, semanal aos sábados) via o argumento opcional `CHANGES_S3_PATH` — um caminho `s3://bucket/key` com a lista de IDs sinalizados pelo `/movie/changes`/`/tv/changes` do TMDB como alterados numa janela de data recente, **independente do ano de lançamento**. Fecha o gap de staleness que os modos semanal/mensal não cobrem (títulos com `year < ano_atual - 1` nunca são re-tocados por eles).

Quando `CHANGES_S3_PATH` está presente, o `main()` entra num ramo antecipado (mesmo padrão do argumento opcional `FORCE_REFETCH`) que substitui inteiramente o fluxo `YEAR`/`END_YEAR`:

1. `fetch_ids_from_changes_file()` lê a lista de IDs do S3 (gravada pela `lambda_api`)
2. `resolve_years_for_changed_ids()` cruza os IDs com a tabela discover via Athena para descobrir o `year` de cada um — a tabela discover é a "base existente" do catálogo: IDs que não constam nela nunca cruzaram a régua de popularidade do `/discover` e são **descartados** (este fluxo nunca expande o catálogo). A lista completa de descartados (não só a contagem) é gravada em `s3://{s3_bucket_temp}/tmdb/changes/{content_type}/discarded_{data}.json` para investigação manual futura
3. `process_changed_ids()` orquestra o refresh: chama `collect_and_write_details()` com todos os IDs resolvidos (sem year — a função já deriva o ano do `release_date`/`first_air_date` de cada resposta), agrupa os IDs por `year` para `collect_and_write_watch_providers()` (que exige `year` explícito por partição), e roda `repair_details_duplicates`/`repair_watch_providers_duplicates` por ano afetado ao final — mesma proteção contra corrida de escrita já usada no fluxo normal quando `year == end_year`
4. Aciona o Glue Data Quality para cada ano afetado

Este modo **nunca** escreve na tabela discover (`repair_discover_duplicates` não é chamado) nem aciona o Glue AGG (já roda no ciclo normal semanal/mensal/anual — rodá-lo a cada execução de changes seria redundante).

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Argumentos: `MEDIA_TYPE`, `YEAR`/`END_YEAR` (opcionais — ausentes no modo changes), `DATABASE`, nomes dos buckets e jobs, `FORCE_REFETCH` (opcional, default `false`), `TRANSLATE_PROVIDER` (opcional, default `"google"` — serviço de tradução primário; o outro é usado automaticamente como fallback — ver `resolve_translate_fn` em `shared_utils.traducao`), `CHANGES_S3_PATH` (opcional — presente apenas no modo changes, ver seção acima) |
| **Leitura** | Athena (IDs da tabela discover na SOT), Secrets Manager (chave API), API TMDB; S3 TEMP (lista de IDs mudados, modo changes) |
| **Escrita** | S3 SOT — tabelas `tb_details_*` e `tb_watch_providers_*` como Parquet + Glue Catalog; S3 TEMP — `tmdb/changes/{content_type}/discarded_{data}.json` (IDs descartados no modo changes) |
| **Aciona** | Glue Data Quality (por tabela gravada) + Glue AGG (apenas na última execução de séries, fluxo normal — não no modo changes) |

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
| `_add_translations_pt(df, translate_fn=None, previous_df=None, detect_fn=None)` | Prioriza overview pt-BR do TMDB; em seguida reaproveita `overview_pt` existente via `reuse_existing_translation` (`shared_utils.traducao`) quando `overview_en` não mudou. O resto (detecção de idioma da fonte e do resultado, cópia direta, tradução via `translate_fn`, teto de tentativas, flag de pendência) é responsabilidade de `shared_utils.traducao.resolve_pt_translation` — grava `overview_detected_language_en`, `overview_detected_language_pt`, `overview_pt`, `overview_translation_attempts` e `overview_needs_translation` |
| `_add_translations_keywords_pt(df, translate_fn=None, previous_df=None, detect_fn=None)` | Reaproveita `keywords_pt` existente via `reuse_existing_translation` quando `keywords` não mudou (sem tradução nativa do TMDB para keywords — diferente de overview/tagline). O resto do fluxo é responsabilidade de `resolve_pt_translation` — grava `keywords_detected_language_en`, `keywords_detected_language_pt`, `keywords_pt`, `keywords_translation_attempts` e `keywords_needs_translation` |
| `_add_translations_tagline_pt(df, translate_fn=None, previous_df=None, detect_fn=None)` | Prioriza tagline pt-BR do TMDB; em seguida reaproveita `tagline_pt` existente via `reuse_existing_translation` quando `tagline` não mudou. O resto do fluxo é responsabilidade de `resolve_pt_translation` — grava `tagline_detected_language_en`, `tagline_detected_language_pt`, `tagline_pt`, `tagline_translation_attempts` e `tagline_needs_translation` |
| `_fetch_collections_pt_br(api_key, collection_ids)` | Busca nomes de coleções em pt-BR na API do TMDB via chamadas paralelas |
| `_add_collection_name_pt(df, api_key)` | Adiciona coluna `collection_name_pt` ao DataFrame de detalhes de filmes |
| `collect_and_write_details(ids, ..., translate_provider="google")` | Faz chamadas paralelas e grava tabela de detalhes. Antes de traduzir, lê o S3 uma única vez por partição `year` afetada, separando os registros existentes em `df_existing_delta` (ids do delta atual, usados como cache de tradução) e `df_existing_keep` (ids fora do delta, preservados no merge final) — a mesma leitura alimenta as duas finalidades. Resolve o `translate_fn` (via `resolve_translate_fn(translate_provider, translate_text, translate_text_aws)`) e o `detect_fn` (via `resolve_detect_language_fn(detect_language_langdetect, detect_language_aws)`, passando as referências locais para preservar os mocks de teste) uma vez por execução e passa, junto com `df_existing_delta`, às 3 `_add_translations_*` |
| `collect_and_write_watch_providers(ids, ...)` | Faz chamadas paralelas e grava tabela de watch providers |
| `_repair_partition_duplicates(...)` | Implementação compartilhada pelos três `repair_*` abaixo: lê a partição `year` via S3, aplica `drop_duplicates` com a chave/critério de desempate recebidos como parâmetro e regrava apenas se houver mudanças |
| `repair_discover_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id)` mantendo o registro de maior `popularity` e regrava apenas se houver mudanças |
| `repair_watch_providers_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id, provider_type, provider_id)` mantendo o `updated_date` mais recente e regrava apenas se houver mudanças |
| `repair_details_duplicates(...)` | Lê a partição `year` via S3, aplica `drop_duplicates(id)` mantendo o registro com `processed_date` mais recente e regrava apenas se houver mudanças |
| `fetch_ids_from_changes_file(s3_path)` | Lê o JSON de IDs mudados gravado pela `lambda_api` no bucket TEMP (modo changes) |
| `resolve_years_for_changed_ids(database, table_discover, ids, s3_bucket_temp, content_type, chunk_size=500)` | Cruza IDs mudados com a tabela discover via Athena (em lotes) para descobrir o `year` de cada um; IDs sem match são descartados do catálogo e gravados por completo em S3 (`discarded_{data}.json`) para investigação manual |
| `process_changed_ids(...)` | Orquestra o modo changes: resolve years, reaproveita `collect_and_write_details`/`collect_and_write_watch_providers` e os `repair_*` por ano afetado; retorna a lista de anos afetados |

## Funções compartilhadas (`shared_utils/`)

Importadas do pacote `shared_utils`, reutilizadas por múltiplos componentes do pipeline:

| Função | Origem | Responsabilidade |
|---|---|---|
| `api_get(url, params, max_retries)` | `shared_utils.api_client` | GET com retry/backoff para lidar com rate limits de APIs |
| `get_api_secret(secret_arn, key_name)` | `shared_utils.api_client` | Busca um segredo no Secrets Manager |
| `trigger_glue_job(job_name, **arguments)` | `shared_utils.triggers` | Dispara qualquer job Glue (DQ, AGG) com argumentos dinâmicos |
| `translate_text(text, context="")` | `shared_utils.traducao_google` (reexportada em `shared_utils.traducao`) | Traduz texto para PT via Google Translate com detecção automática do idioma de origem; retorna o texto original em caso de falha |
| `translate_text_aws(text, region="us-east-1")` | `shared_utils.traducao_aws` (reexportada em `shared_utils.traducao`) | Traduz texto para PT via AWS Translate (boto3); retorna o texto original em caso de falha |
| `resolve_translate_fn(provider, translate_google=translate_text, translate_aws=translate_text_aws, aws_fallback_max_chars=6_000)` | `shared_utils.traducao` | Resolve `TRANSLATE_PROVIDER` (`"google"` ou `"aws"`) para uma função composta primário+fallback — este job usa `"google"` por padrão, com AWS Translate como fallback capado por caracteres. Levanta `ValueError` para qualquer outro valor |
| `translate_in_parallel(values, translate_fn, max_workers)` | `shared_utils.traducao` | Aplica `translate_fn` a cada valor em paralelo via `ThreadPoolExecutor`; usada por `resolve_pt_translation` |
| `resolve_pt_translation(df, source_column, target_column, detected_language_en_column, detected_language_pt_column, translation_attempts_column, detect_fn, translate_fn, max_workers, max_attempts, needs_translation_column=None)` | `shared_utils.traducao` | Detecta o idioma da fonte e do resultado (só onde ainda vazios), copia a fonte direto quando ela já é `"pt"`, traduz as linhas elegíveis (fonte preenchida, idioma do resultado ainda diferente de `"pt"`, tentativas abaixo do teto), incrementa o contador de tentativas e redetecta o idioma do resultado só nas linhas recém-traduzidas. Com `needs_translation_column` informado (usado pelos 3 campos deste job), grava também um booleano de "ainda não está em português" sem o teto de tentativas. Devolve `(df, quantidade traduzida com sucesso)`. Compartilhada com `scripts/backfill_traducao.py` e `glue_etl` para evitar que as cópias divirjam |
| `reuse_existing_translation(df, previous_df, source_column, target_column, key_column="id")` | `shared_utils.traducao` | Pré-preenche `target_column` do `df` novo com o valor já persistido (`previous_df`) quando `source_column` não mudou para o mesmo `key_column`. Não sobrescreve valor já preenchido (prioridade da tradução nativa do TMDB); registros novos sem histórico ou schema antigo sem a coluna não são afetados. Compartilhada com `glue_etl` (que usa `key_column="iso_3166_1"`/`"iso_639_1"` para a tabela `configuration`) |
| `make_capped_fallback(fallback_fn, max_chars, on_over_budget)` | `shared_utils.traducao` | Envolve `fallback_fn` com orçamento de caracteres thread-safe; usado tanto pelo fallback AWS Translate de `resolve_translate_fn` quanto pelo fallback AWS Comprehend de `resolve_detect_language_fn` |
| `detect_language_langdetect(text)` | `shared_utils.idioma_langdetect` | Detecção de idioma local via `langdetect` (offline, sem custo). Devolve `None` em texto vazio, `LangDetectException` (comum em textos curtos, ex.: keywords) ou erro inesperado |
| `detect_language_aws(text, region="us-east-1")` | `shared_utils.idioma_aws` | Detecção de idioma via AWS Comprehend (`DetectDominantLanguage`) — usada como fallback do `langdetect`. A permissão IAM já existe na role deste job (concedida para o AWS Translate acionar Comprehend internamente) |
| `resolve_detect_language_fn(detect_local=detect_language_langdetect, detect_aws=detect_language_aws, aws_fallback_max_chars=6_000, provider=translate_provider)` | `shared_utils.idioma` | Resolve a função composta de detecção, espelhando `provider` de `resolve_translate_fn`: com `TRANSLATE_PROVIDER="google"`, `langdetect` primeiro e AWS Comprehend como fallback capado por caracteres se o local falhar (devolver `None`); com `"aws"`, Comprehend primeiro (sem cap) e `langdetect` como fallback. Montada com o mesmo `translate_provider` de `resolve_translate_fn` |
| `get_resolved_option(args)` | `shared_utils.glue_helpers` | Wrapper de `getResolvedOptions` — converte lista de nomes de argumentos em dicionário nome→valor |
| `configure_glue_logging()` | `shared_utils.glue_helpers` | Configura o logging padrão dos jobs Glue (stdout, nível INFO, formato com timestamp) |

## Tecnologias

- **requests** + **ThreadPoolExecutor** — chamadas paralelas à API com controle de concorrência
- **deep_translator** (GoogleTranslator, `source="auto"`) — serviço de tradução default deste job (`TRANSLATE_PROVIDER="google"`, caminho automático via EventBridge) para sinopses, keywords e taglines quando a tradução pt-BR não existe no TMDB, com detecção automática do idioma de origem
- **AWS Translate** (via boto3) — alternativa via `TRANSLATE_PROVIDER="aws"`; usado automaticamente como fallback capado por caracteres quando o Google falha, mesmo com `TRANSLATE_PROVIDER="google"`; sem custo de API key/secret (usa a role IAM do job)
- **langdetect** — detecção local de idioma (offline, sem custo) do texto fonte (`<campo>_detected_language_en`) e do resultado (`<campo>_detected_language_pt`); usada também para pular a tradução quando a fonte já está em português (evita retradução infinita)
- **AWS Comprehend** (`DetectDominantLanguage`, via boto3) — fallback do `langdetect` quando este falha, capado por orçamento de caracteres; usa a mesma permissão IAM já concedida para o AWS Translate
- **awswrangler** — consultas Athena e escrita Parquet
- **boto3** — Secrets Manager, AWS Translate e acionamento de jobs Glue
