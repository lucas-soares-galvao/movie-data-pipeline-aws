# Testes — glue_details

## O que é testado

Testa a função `main()` em `app/glue_details/main.py` e as funções utilitárias em `app/glue_details/src/utils.py`. O foco é verificar: coleta paralela de detalhes via API TMDB, lógica de acionamento condicional do Glue AGG (apenas na última execução) e escrita das tabelas de detalhes e watch providers na SOT. Todas as dependências externas (Athena, Secrets Manager, API TMDB, S3) são substituídas por **mocks** — objetos falsos que simulam o comportamento esperado sem fazer chamadas reais, mantendo os testes rápidos, gratuitos e isolados.

## Estrutura

```
test/glue_details/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes da função main()
└── test_utils.py             # Testes das funções utilitárias
```

## Fixtures (`conftest.py`)

O `conftest.py` desta suite **não define nenhuma `@pytest.fixture`**. Ele só faz duas coisas: adiciona `app/glue_details/` ao início de `sys.path` (para que `from src.utils import ...` funcione nos testes) e cria stubs dos módulos `awsglue`/`awsglue.utils` (que só existem no runtime do Glue), substituindo `getResolvedOptions` por um `MagicMock()`.

Em vez de fixtures compartilhadas, os testes usam `unittest.mock.patch.object(...)` inline em cada caso de teste, mais alguns helpers locais definidos diretamente em `test_utils.py` (ex.: `_BASE`, `_mock_movie_response`, `_mock_tv_response`) para montar respostas simuladas da API TMDB.

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
| `test_force_refetch_skips_existing_ids_check` | Com `FORCE_REFETCH=true`, `fetch_existing_ids_from_details` não é chamado e todos os IDs do discover são rebuscados |

### Acionamento condicional do repair e do Glue AGG

| Teste | O que verifica |
|---|---|
| `test_triggers_agg_when_tv_and_last_year` | AGG é acionado quando `media_type="tv"` e `year == end_year` |
| `test_repair_called_before_agg_when_tv_and_last_year` | Os três repairs são chamados na ordem `discover → watch_providers → details → agg` quando tv+end_year |
| `test_repair_called_for_movie_at_last_year` | `repair_details_duplicates` é chamado para `media_type="movie"` quando `year == end_year` |
| `test_repair_not_called_when_not_last_year` | Nenhum dos três repairs é chamado quando `year != end_year` |
| `test_repair_discover_duplicates_called_at_last_year` | `repair_discover_duplicates` é chamado com os argumentos corretos quando `year == end_year` |
| `test_repair_watch_providers_duplicates_called_at_last_year` | `repair_watch_providers_duplicates` é chamado com os argumentos corretos quando `year == end_year` |
| `test_does_not_trigger_agg_for_movie` | AGG **não** é acionado para `media_type="movie"` |
| `test_does_not_trigger_agg_for_tv_non_last_year` | AGG **não** é acionado para séries quando `year != end_year` |

## Casos de teste — `test_utils.py`

Testa as funções individuais:

- `_extract_cast` (`TestExtractCast`): top 5 por `order`, menos que o limite, cast vazio, sem chave `cast`, limite customizado
- `_extract_director` (`TestExtractDirector`): diretor único, múltiplos diretores, sem diretor, crew vazio
- `_extract_writers` (`TestExtractWriters`): roteirista único, múltiplos (Screenplay + Writer), deduplicação por nome, crew vazio
- `_extract_composer` (`TestExtractComposer`): compositor único, múltiplos, crew vazio
- `_extract_keywords` (`TestExtractKeywords`): formato movie (chave `keywords`), formato tv (chave `results`), dict vazio, lista vazia
- `_extract_certification_br_movie` (`TestExtractCertificationBrMovie`): encontra BR, sem BR, BR sem certification, dict vazio
- `_extract_certification_br_tv` (`TestExtractCertificationBrTv`): encontra BR, sem BR, rating vazio
- `_extract_trailer_url` (`TestExtractTrailerUrl`): trailer oficial do YouTube, fallback para não-oficial, sem YouTube, sem trailer, dict vazio
- `_extract_production_companies` (`TestExtractProductionCompanies`): produtoras comma-separated, lista vazia, entrada None
- `_extract_creators` (`TestExtractCreators`): criadores comma-separated, lista vazia
- `_extract_networks` (`TestExtractNetworks`): networks comma-separated, lista vazia
- `_extract_producers` (`TestExtractProducers`): produtor único, produtor+executivo, deduplicação por nome, limite top 3, sem produtor, crew vazio
- `_extract_cinematographer` (`TestExtractCinematographer`): cinematógrafo único, múltiplos, sem cinematógrafo, crew vazio
- `_extract_editor` (`TestExtractEditor`): montador único, múltiplos, sem montador, crew vazio
- `_extract_production_countries` (`TestExtractProductionCountries`): múltiplos países, lista vazia, entrada None
- `_extract_recommended_titles` (`TestExtractRecommendedTitles`): formato movie (title), formato tv (name), limite customizado, dict vazio, results vazio
- `_extract_recommended_ids` (`TestExtractRecommendedIds`): extração de IDs, limite customizado, dict vazio, results vazio, result sem campo id
- `_extract_similar_titles` (`TestExtractSimilarTitles`): formato movie (title), formato tv (name), dict vazio
- `_extract_similar_ids` (`TestExtractSimilarIds`): extração de IDs, dict vazio, result sem campo id
- `_extract_alternative_titles` (`TestExtractAlternativeTitles`): formato movie (titles key), formato tv (results key), dict vazio
- `_extract_pt_br_translation` (`TestExtractPtBrTranslation`): extrai overview/tagline pt-BR do array de translations, retorna None quando sem pt-BR, ignora pt-PT, ignora overview vazio
- `_add_translations_pt` (`TestAddTranslationsOverviewPt`): prioriza tradução pt-BR do TMDB, fallback para Google Translate quando TMDB não tem, traduz mesmo quando `original_language` já é `pt` (não é critério de elegibilidade), loga resumo "N registros traduzidos com sucesso (overview_pt)" em INFO, retenta quando `overview_pt_tmdb` fica igual a `overview_en`, grava `overview_detected_language_en` (a partir de `overview_en`) e `overview_detected_language_pt` (a partir do resultado final em `overview_pt` — `"pt"` para nativo TMDB/sucesso Google, diferente de `"pt"` para falha/fonte vazia), copia `overview_en` direto para `overview_pt` sem chamar tradução quando o idioma já é detectado como `"pt"` (otimização contra retradução infinita), e grava `overview_needs_translation` (`True` quando a tradução falha, `False` quando o resultado já está em português)
- `_add_translations_keywords_pt` (`TestAddTranslationsKeywordsPt`): traduz via Google Translate, traduz mesmo quando `original_language` já é `pt` (TMDB não localiza keywords), não traduz quando `keywords` vazia (`keywords_detected_language_pt` fica nulo), copia direto sem chamar tradução quando idioma já detectado como `"pt"`, e grava `keywords_needs_translation` (`True` quando a tradução falha, `False` quando `keywords` está vazia)
- `_add_translations_tagline_pt` (`TestAddTranslationsTaglinePt`): prioriza tradução pt-BR do TMDB, fallback para Google Translate quando TMDB não tem, ignora vazia/nula, traduz mesmo quando `original_language` já é `pt` (não é critério de elegibilidade), retenta quando `tagline_pt_tmdb` fica igual a `tagline`, copia direto sem chamar tradução quando idioma já detectado como `"pt"`, e grava `tagline_needs_translation` (`True` quando a tradução falha, `False` quando o resultado já está em português)
- `_extract_production_countries_iso` (`TestExtractProductionCountriesIso`): extrai códigos ISO, retorna None para lista vazia e None
- `_extract_spoken_languages` (`TestExtractSpokenLanguages`): prioriza `name` nativo sobre `english_name`, fallback para `english_name`
- `_extract_spoken_languages_iso` (`TestExtractSpokenLanguagesIso`): extrai códigos ISO 639-1, ignora entradas sem ISO, retorna None para lista vazia/None
- `fetch_ids_from_sot`: query Athena monta SQL correto com filtro de ano
- `fetch_existing_ids_from_details`: SQL **não** contém filtro de `year` — detecta IDs processados em qualquer partição no mês atual; retorna `[]` em caso de erro (tabela inexistente na primeira execução)
- `fetch_ids_stale_watch_providers`: SQL usa LEFT JOIN e condição mensal; retorna `[]` em caso de erro
- `collect_and_write_details`: chamadas paralelas retornam o DataFrame esperado, IDs inválidos são ignorados; merge com dados existentes preserva IDs fora do batch e substitui IDs re-escritos; `drop_duplicates` garante unicidade no DataFrame antes da escrita; usa `mode="overwrite_partitions"`; falha no `read_parquet` grava apenas novos registros sem erro; não escreve nada quando todos os IDs falham (`test_does_not_write_when_all_ids_fail`); não escreve nada quando todos os registros ficam sem `year` após o `dropna` (`test_does_not_write_when_all_records_missing_year` — regressão do bug `EmptyDataFrame` no `wr.s3.to_parquet`); prioriza tradução pt-BR do TMDB para overview e tagline (movie com translations); fallback via `translate_fn` (`translate_provider="google"` no teste, patchando `translate_text`) quando TMDB não tem pt-BR (TV sem translations) — em produção o default é `translate_provider="aws"`; campos intermediários (`overview_pt_tmdb`, `tagline_pt_tmdb`) não aparecem no DataFrame final; grava `collection_id`, `collection_name_pt`, `production_countries_iso` para filmes; `production_countries_iso` como array de ISO codes para lookup no AGG (a gravação de `spoken_languages_iso` é coberta em nível de extração por `TestExtractSpokenLanguagesIso`, não neste teste de escrita); **cache de tradução entre execuções:** não retraduz quando a fonte (`overview_en`/`tagline`/`keywords`) não mudou desde o registro existente no S3 (`test_nao_retraduz_quando_fonte_nao_mudou`); retraduz só o campo cuja fonte mudou, reaproveitando o cache dos demais (`test_retraduz_apenas_campo_cuja_fonte_mudou`, com `translate_provider="google"`); tradução nativa do TMDB no run atual sobrepõe o cache mesmo com fonte igual (`test_traducao_nativa_tmdb_sobrepoe_cache`); lê o S3 uma única vez por partição `year`, reaproveitada tanto para o cache de tradução quanto para o merge final (`test_le_s3_uma_unica_vez_por_particao_year`); as 9 colunas de diagnóstico (`overview_detected_language_en`/`_pt`/`overview_translation_attempts`, `tagline_detected_language_en`/`_pt`/`tagline_translation_attempts`, `keywords_detected_language_en`/`_pt`/`keywords_translation_attempts`) aparecem no DataFrame final gravado, e as antigas `overview_translated_pt_br`/`tagline_translated_pt_br`/`keywords_translated_pt_br` não existem mais, tanto para filmes quanto para séries; registros preservados (`df_existing_keep`) com o schema pt-BR pré-rename (`overview_idioma_detectado_en/pt`, `overview_tentativas_traducao`, `overview_precisa_traducao`) têm essas colunas descartadas do DataFrame final, sem afetar os demais registros do merge (`test_descarta_colunas_legadas_de_registros_preservados`)
- `repair_details_duplicates` (`TestRepairDetailsDuplicates`): sem duplicatas → não reescreve; S3 inacessível → não propaga exceção; partição vazia → não reescreve; com duplicatas → mantém `dt_processamento` mais recente por ID; usa `overwrite_partitions`
- `repair_discover_duplicates` (`TestRepairDiscoverDuplicates`): sem duplicatas → não reescreve; S3 inacessível → não propaga exceção; partição vazia → não reescreve; com duplicatas → mantém registro de maior `popularity`; usa `overwrite_partitions`
- `repair_watch_providers_duplicates` (`TestRepairWatchProvidersDuplicates`): sem duplicatas → não reescreve; S3 inacessível → não propaga exceção; com duplicatas → deduplicação pela chave `(id, provider_type, provider_id)`, mantendo `dt_atualizacao` mais recente; rebranding de provider (mesmo `provider_id`, nomes distintos) é tratado como duplicata; usa `overwrite_partitions`
- `collect_and_write_watch_providers` (`TestCollectAndWriteWatchProviders`): grava com partição `["year"]`; não escreve quando nenhum provedor é encontrado; IDs que falham na API são pulados sem propagar exceção; valor do ano é preservado no DataFrame gravado

### `TestExtractCast`

| Teste | O que verifica |
|---|---|
| `test_top_5_por_ordem` | Extrai top 5 atores ordenados por `order` (billing order) |
| `test_menos_que_limite` | Funciona com menos atores do que o limite |
| `test_cast_vazio` | Retorna `None` para `cast` vazio |
| `test_sem_cast` | Retorna `None` quando não há chave `cast` |
| `test_limite_customizado` | Respeita o parâmetro `limite` customizado |

### `TestExtractDirector`

| Teste | O que verifica |
|---|---|
| `test_diretor_unico` | Extrai um único diretor (job `Director` no crew) |
| `test_multiplos_diretores` | Extrai múltiplos diretores |
| `test_sem_diretor` | Retorna `None` quando não há diretor na crew |
| `test_crew_vazio` | Retorna `None` para crew vazia |

### `TestExtractKeywords`

| Teste | O que verifica |
|---|---|
| `test_formato_movie` | Extrai keywords via chave `keywords` (filmes) |
| `test_formato_tv` | Extrai keywords via chave `results` (séries) |
| `test_vazio` | Retorna `None` para dict vazio |
| `test_lista_vazia` | Retorna `None` para lista de keywords vazia |

### `TestExtractCertificationBrMovie`

| Teste | O que verifica |
|---|---|
| `test_encontra_br` | Extrai a certificação do release BR (`iso_3166_1='BR'`) |
| `test_sem_br` | Retorna `None` quando não há release BR |
| `test_br_sem_certification` | Retorna `None` quando o release BR tem `certification` vazia |
| `test_vazio` | Retorna `None` para dict vazio |

### `TestExtractCertificationBrTv`

| Teste | O que verifica |
|---|---|
| `test_encontra_br` | Extrai o `rating` BR (`iso_3166_1='BR'`) |
| `test_sem_br` | Retorna `None` quando não há rating BR |
| `test_rating_vazio` | Retorna `None` quando o rating BR está vazio |

### `TestExtractTrailerUrl`

| Teste | O que verifica |
|---|---|
| `test_trailer_oficial` | Prioriza trailer oficial do YouTube |
| `test_fallback_nao_oficial` | Usa trailer não-oficial do YouTube quando não há oficial |
| `test_sem_youtube` | Retorna `None` quando o único trailer não é do YouTube |
| `test_sem_trailer` | Retorna `None` quando só há vídeos do tipo `Teaser` |
| `test_vazio` | Retorna `None` para dict vazio |

### `TestExtractProductionCompanies`

| Teste | O que verifica |
|---|---|
| `test_produtoras` | Extrai nomes de produtoras comma-separated |
| `test_lista_vazia` | Retorna `None` para lista vazia |
| `test_none` | Retorna `None` para entrada `None` |

### `TestExtractCreators`

| Teste | O que verifica |
|---|---|
| `test_criadores` | Extrai nomes de criadores comma-separated |
| `test_vazio` | Retorna `None` para lista vazia |

### `TestExtractNetworks`

| Teste | O que verifica |
|---|---|
| `test_networks` | Extrai nomes de redes de TV comma-separated |
| `test_vazio` | Retorna `None` para lista vazia |

### `TestExtractProducers`

| Teste | O que verifica |
|---|---|
| `test_produtor_unico` | Extrai um único produtor (job `Producer`) |
| `test_produtor_e_executivo` | Extrai produtor + produtor executivo |
| `test_deduplica_mesmo_nome` | Mesmo nome com jobs diferentes conta uma só vez |
| `test_limite_top_3` | Limita a 3 produtores quando há mais de 3 |
| `test_sem_produtor` | Retorna `None` quando não há produtor na crew |
| `test_crew_vazio` | Retorna `None` para crew vazia |

### `TestExtractCinematographer`

| Teste | O que verifica |
|---|---|
| `test_cinematografo_unico` | Extrai um único diretor de fotografia |
| `test_multiplos_cinematografos` | Extrai múltiplos diretores de fotografia |
| `test_sem_cinematografo` | Retorna `None` quando não há cinematógrafo |
| `test_crew_vazio` | Retorna `None` para crew vazia |

### `TestExtractEditor`

| Teste | O que verifica |
|---|---|
| `test_montador_unico` | Extrai um único editor/montador |
| `test_multiplos_montadores` | Extrai múltiplos montadores |
| `test_sem_montador` | Retorna `None` quando não há montador |
| `test_crew_vazio` | Retorna `None` para crew vazia |

### `TestExtractProductionCountries`

| Teste | O que verifica |
|---|---|
| `test_paises` | Extrai múltiplos países de produção |
| `test_vazio` | Retorna `None` para lista vazia |
| `test_none` | Retorna `None` para entrada `None` |

### `TestExtractRecommendedTitles`

| Teste | O que verifica |
|---|---|
| `test_movie` | Extrai títulos recomendados via chave `title` (filmes) |
| `test_tv` | Extrai títulos recomendados via chave `name` (séries) |
| `test_limite` | Respeita o limite customizado (top N) |
| `test_vazio` | Retorna `None` para dict vazio |
| `test_results_vazio` | Retorna `None` para `results` vazio |

### `TestExtractSimilarTitles`

| Teste | O que verifica |
|---|---|
| `test_movie` | Extrai títulos similares via chave `title` (filmes) |
| `test_tv` | Extrai títulos similares via chave `name` (séries) |
| `test_vazio` | Retorna `None` para dict vazio |

### `TestExtractAlternativeTitles`

| Teste | O que verifica |
|---|---|
| `test_movie` | Extrai títulos alternativos via chave `titles` (filmes) |
| `test_tv` | Extrai títulos alternativos via chave `results` (séries) |
| `test_vazio` | Retorna `None` para dict vazio |

### `TestExtractPtBrTranslation`

| Teste | O que verifica |
|---|---|
| `test_extrai_overview_e_tagline_pt_br` | Extrai overview e tagline da tradução pt-BR no array de translations |
| `test_retorna_none_quando_sem_pt_br` | Retorna `None` para ambos quando pt-BR não existe |
| `test_retorna_none_quando_translations_vazio` | Retorna `None` para dict vazio (sem chave `translations`) |
| `test_ignora_pt_de_portugal` | Ignora tradução pt-PT (iso_3166_1='PT'), retorna `None` |
| `test_ignora_overview_vazio` | Retorna `None` para overview vazio, mas extrai tagline |

### `TestAddTranslationsOverviewPt`

| Teste | O que verifica |
|---|---|
| `test_prioriza_tmdb_pt_br` | Usa `overview_pt_tmdb` quando presente, sem chamar Google Translate |
| `test_fallback_para_google_translator` | Traduz via Google Translate quando não há `overview_pt_tmdb` |
| `test_traduz_mesmo_com_idioma_original_pt` | Chama `translate_text` mesmo quando `original_language == "pt"` — não é critério de elegibilidade (idioma detectado do texto é forçado para `"en"` via `detect_fn`, isolando do comportamento real do `langdetect`) |
| `test_loga_resumo_de_sucesso` | Loga `"1 registros traduzidos com sucesso (overview_pt)."` em INFO |
| `test_nao_conta_como_sucesso_quando_traducao_falha_e_mantem_original` | `translate_text` devolve o original em caso de falha; log reporta `"0 registros traduzidos com sucesso"` |
| `test_retenta_quando_overview_pt_tmdb_igual_a_overview_en` | Caso de borda: `overview_pt_tmdb` idêntico a `overview_en` é reenviado ao Google Translate (mesma regra de retry do backfill) |
| `test_idioma_detectado_en_calculado_a_partir_da_fonte` | `overview_detected_language_en` chama `detect_fn` com `overview_en` (a fonte) |
| `test_idioma_detectado_pt_calculado_a_partir_do_resultado` | `overview_detected_language_pt` chama `detect_fn` com o valor final de `overview_pt` (o resultado), não com `overview_en` |
| `test_idioma_detectado_en_none_quando_fonte_vazia` | `overview_en` vazio/nulo → `overview_detected_language_en` fica nulo |
| `test_idioma_detectado_pt_none_quando_destino_vazio` | `overview_pt` continua vazio (sem TMDB/cache/tradução) → `overview_detected_language_pt` fica nulo |
| `test_idioma_detectado_pt_e_pt_apos_sucesso_google` | `overview_detected_language_pt` é `"pt"` após tradução via Google bem-sucedida |
| `test_idioma_detectado_pt_nao_e_pt_quando_traducao_falha` | `overview_detected_language_pt` não é `"pt"` quando a tradução falha e mantém o texto original |
| `test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao` | Fonte com idioma detectado `"pt"` (sem TMDB nativo/cache) é copiada direto para `overview_pt`; `translate_fn` mockado **não** é chamado; `overview_detected_language_pt` fica `"pt"` |
| `test_overview_precisa_traducao_true_quando_traducao_falha` | `overview_needs_translation` é `True` quando a tradução falha (resultado igual ao original, idioma continua diferente de `"pt"`) |
| `test_overview_precisa_traducao_false_quando_ja_em_portugues` | `overview_needs_translation` é `False` quando `overview_pt` já está em português (nativo do TMDB) |

### `TestAddTranslationsKeywordsPt`

| Teste | O que verifica |
|---|---|
| `test_traduz_keywords` | Traduz `keywords` via Google Translate |
| `test_traduz_mesmo_com_idioma_original_pt` | Chama `translate_text` mesmo quando `original_language == "pt"` — não é critério de elegibilidade |
| `test_nao_traduz_quando_keywords_vazias` | `keywords_pt` fica nulo quando `keywords` está vazia/nula; `keywords_detected_language_pt` fica nulo |
| `test_idioma_detectado_en_calculado_a_partir_da_fonte` | `keywords_detected_language_en` chama `detect_fn` com `keywords` (a fonte) |
| `test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao` | Fonte com idioma detectado `"pt"` é copiada direto para `keywords_pt`, sem chamar `translate_fn`; `keywords_detected_language_pt` fica `"pt"` |
| `test_keywords_precisa_traducao_true_quando_traducao_falha` | `keywords_needs_translation` é `True` quando a tradução falha |
| `test_keywords_precisa_traducao_false_quando_vazias` | `keywords_needs_translation` é `False` quando `keywords` está vazia/nula (nada a traduzir) |

### `TestAddTranslationsTaglinePt`

| Teste | O que verifica |
|---|---|
| `test_prioriza_tmdb_pt_br` | Usa `tagline_pt_tmdb` quando presente, sem chamar Google Translate |
| `test_fallback_para_google_translator` | Traduz via Google Translate quando não há `tagline_pt_tmdb` |
| `test_nao_traduz_quando_tudo_vazio` | `tagline`/`tagline_pt_tmdb` vazios → `tagline_pt` fica nulo, `tagline_detected_language_pt` fica nulo para todos os registros |
| `test_traduz_mesmo_com_idioma_original_pt` | Chama `translate_text` mesmo quando `original_language == "pt"` (idioma detectado do texto forçado para `"en"`) |
| `test_retenta_quando_tagline_pt_tmdb_igual_a_tagline` | Caso de borda: `tagline_pt_tmdb` idêntico a `tagline` é reenviado ao Google Translate |
| `test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao` | Fonte com idioma detectado `"pt"` é copiada direto para `tagline_pt`, sem chamar `translate_fn`; `tagline_detected_language_pt` fica `"pt"` |
| `test_tagline_precisa_traducao_true_quando_traducao_falha` | `tagline_needs_translation` é `True` quando a tradução falha |
| `test_tagline_precisa_traducao_false_quando_ja_em_portugues` | `tagline_needs_translation` é `False` quando `tagline_pt` já está em português (nativo do TMDB) |

As classes abaixo testam funções auxiliares de mais baixo nível que o doc anterior não cobria:

### `TestFetchTmdbDetails`

| Teste | O que verifica |
|---|---|
| `test_calls_movie_endpoint` | URL contém `/movie/{id}` para `content_type="movie"` |
| `test_calls_tv_endpoint` | URL contém `/tv/{id}` para `content_type="tv"` |
| `test_returns_json_response` | Retorna o JSON da resposta HTTP sem transformação |

### `TestFetchTmdbWatchProviders`

| Teste | O que verifica |
|---|---|
| `test_calls_movie_watch_providers_endpoint` | URL contém `/movie/{id}/watch/providers` |
| `test_calls_tv_watch_providers_endpoint` | URL contém `/tv/{id}/watch/providers` |
| `test_returns_br_section` | Retorna apenas o dicionário da seção `BR` do payload da API |

### `TestParseWatchProviders`

| Teste | O que verifica |
|---|---|
| `test_returns_empty_list_for_empty_br_data` | Retorna `[]` quando não há dados de BR |
| `test_generates_one_record_per_flatrate_provider` | Gera um registro por provedor `flatrate`, com `provider_type`, `provider_name`, `id` e `year` corretos |
| `test_generates_records_for_multiple_provider_types` | Processa `flatrate`, `rent` e `buy` gerando registros distintos por tipo |
| `test_ignores_providers_without_name` | Provedores sem `provider_name` são ignorados |

### `TestGetParametersGlue`

| Teste | O que verifica |
|---|---|
| `test_returns_all_required_args` | Retorna os parâmetros obrigatórios do job (`S3_BUCKET_SOT`, databases, tabelas de discover e details, `TABLE_WATCH_PROVIDERS_*`, `AGG_JOB_NAME`, etc.) |

> **Nota:** os testes de `trigger_glue_job`/DQ (`TestTriggerDataQuality`), `get_resolved_option` (`TestGetResolvedOption`), `get_api_secret` (`TestGetApiSecret`) e `reuse_existing_translation` (`TestReuseExistingTranslation`) não vivem mais em `test_utils.py` deste módulo — migraram para `test/shared_src/test_api_client.py`, `test/shared_src/test_glue_helpers.py` e `test/shared_src/test_traducao.py` junto com a extração dessas funções para `shared_utils/`.

## Como executar

```bash
# Apenas os testes do glue_details
pytest test/glue_details/ -v

# Com cobertura
pytest test/glue_details/ --cov=app/glue_details --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).
