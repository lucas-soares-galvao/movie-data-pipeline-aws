# Testes — lightsail_ia

## O que é testado

Testa as funções do agente de recomendação (`app/lightsail_ia/agent.py`), as funções de formatação (`app/lightsail_ia/formatacao.py`) e os componentes de renderização HTML (`app/lightsail_ia/componentes.py`). O `test_agent.py` cobre `recommend()`, `search_titles_spec()`, validação SQL, extração de termos de gênero/provedor para destaque nas badges, cache e logging de tokens. O `test_formatacao.py` cobre as funções puras de formatação (`format_record`, `_format_type`, `_format_genres`, `_format_title_duration`, `_format_release_date`, `_format_theater_end_date`, `_format_rating`). O `test_componentes.py` cobre a renderização de cards e grids (`render_card`, `render_grid`), a priorização de badges por termo destacado (`_prioritize`), a caixa de mensagem de feedback padronizada (`render_feedback`) e a injeção dos scripts `load_audio_timer_script`/`load_countdown_script`/`load_login_button_toggle_script`, incluindo escape XSS e verificação de campos exibidos/ignorados. Os testes usam estilo **pytest** (classes simples, `assert` nativo, `with patch(...)` como context manager). A interface Streamlit (`app.py`) não é testada diretamente — é validada via execução manual. Todas as chamadas externas (LLM e Athena) são substituídas por **mocks** via `unittest.mock` — objetos falsos que simulam respostas do LLM e do banco de dados sem fazer chamadas reais, evitando custos de API e tornando os testes determinísticos.

## Estrutura

```
test/lightsail_ia/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_agent.py             # Testes do agente (LLM, Athena, cache, validação)
├── test_componentes.py       # Testes de renderização HTML (cards e grids)
└── test_formatacao.py        # Testes das funções puras de formatação
```

## Setup (`conftest.py`)

O `conftest.py` configura variáveis de ambiente obrigatórias antes do import de `agent.py` e define uma fixture `autouse` que limpa o cache de WHERE clauses entre testes:

| Variável | Valor de teste |
|---|---|
| `LLM_API_KEY` | `"test-llm-key"` (fallback — `FILMBOT_SECRET_ARN` não é definida em testes) |
| `TRANSCRIPTION_API_KEY` | `"test-transcription-key"` (fallback — `FILMBOT_SECRET_ARN` não é definida em testes) |
| `AWS_REGION` | `"sa-east-1"` |
| `GLUE_DATABASE` | `"db_tmdb_unified_prod"` |
| `SPEC_TABLE` | `"tb_tmdb_discover_unified_prod"` |
| `ATHENA_S3_OUTPUT` | `"s3://test-bucket-temp/athena-results/"` |

| Fixture | Escopo | Descrição |
|---|---|---|
| `_limpar_cache_where` | `autouse` | Limpa `agent._WHERE_CACHE` antes de cada teste para garantir isolamento entre testes |

## Funções auxiliares de mock (`test_agent.py`)

| Função | Descrição |
|---|---|
| `_setup_athena_mock(mock_boto3, rows_data)` | Configura o mock do `boto3` para simular as 3 etapas da API nativa do Athena: `start_query_execution` → `get_query_execution` (polling) → `get_paginator().paginate()`. `rows_data` define as linhas de resultado; `None` retorna apenas o header (resultado vazio). |
| `_mock_litellm(tool_args, reason_content=None)` | Retorna lista com 2 respostas para `side_effect` de `litellm.completion`: Etapa 1 (Function Calling com `tool_args`) e Etapa 3 (motivo, com o conteúdo de `reason_content` — ou `{"titles": []}` por padrão, se `None`). Inclui mock de `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`) para compatibilidade com `_log_token_usage()`. |

## Casos de teste — `test_agent.py`

### `TestValidateWhere` — Validação de segurança da cláusula WHERE

| Teste | O que verifica |
|---|---|
| `test_aceita_clausula_valida` | Aceita e retorna cláusula WHERE válida sem alterações |
| `test_rejeita_ponto_e_virgula` | Rejeita cláusulas com `;` (prevenção de statement injection) |
| `test_rejeita_drop` | Rejeita cláusulas com `DROP` |
| `test_rejeita_delete` | Rejeita cláusulas com `DELETE` |
| `test_rejeita_insert` | Rejeita cláusulas com `INSERT` |
| `test_rejeita_subquery_select` | Rejeita cláusulas com `SELECT` (prevenção de subquery) |
| `test_remove_espacos_nas_pontas` | Remove espaços em branco nas extremidades da cláusula |

### `TestExtractHighlightedTerms` — Extração de termos de gênero/provedor para destaque

Gênero e provedor são extraídos por regex independentes (`_HIGHLIGHT_FIELD_PATTERNS`), sem nenhum branch que dependa dos dois campos juntos — por isso os testes cobrem cada campo isolado nos seus 3 estados de contagem (nenhum/um/mais de um), mais um único caso combinado provando que não há interferência entre eles, mais os cenários de "tipo de menção" (positivo/negativo) e robustez do regex.

| Teste | O que verifica |
|---|---|
| `test_sem_filtro_de_genero_ou_provedor_retorna_listas_vazias` | `where_clause` sem `genre_names`/`streaming_providers` → `{"genres": [], "providers": []}` |
| `test_extrai_um_genero` | Um `LIKE` de gênero → `genres == ["terror"]` |
| `test_extrai_mais_de_um_genero` | Dois `LIKE` ORed de gênero → `genres == ["terror", "comédia"]`, na ordem de aparição |
| `test_extrai_um_provedor` | Um `LIKE` de provedor → `providers == ["netflix"]` |
| `test_extrai_mais_de_um_provedor` | Dois `LIKE` ORed de provedor → `providers == ["netflix", "crunchyroll"]` |
| `test_extrai_genero_e_provedor_juntos_sem_interferencia` | `where_clause` com gênero E provedor → os dois campos populados corretamente no mesmo resultado |
| `test_case_insensitive_lower_e_like` | `LOWER(...)`/`Like` (caixa variada) ainda é reconhecido |
| `test_tolera_espacos_extras` | Espaços extras dentro de `lower( genre_names )  LIKE  '%x%'` não quebram o match |
| `test_not_like_e_excluido` | `NOT LIKE` nunca é destacado (usuário não quer aquele valor) |
| `test_positivo_e_negativo_no_mesmo_campo` | `LIKE '%comédia%' AND NOT LIKE '%terror%'` → só `["comédia"]` |
| `test_overview_nao_conta_como_filtro_de_genero` | `lower(overview) LIKE '%terror%'` não é confundido com filtro de `genre_names` |
| `test_rent_buy_providers_nao_conta_como_filtro_de_streaming` | `lower(rent_buy_providers) LIKE '%netflix%'` não é confundido com filtro de `streaming_providers` |
| `test_termo_duplicado_aparece_uma_vez` | Mesmo termo repetido na `where_clause` aparece uma única vez na lista (dedup) |

### `TestSearchTitlesSpec` — Consulta ao Athena (Etapa 2)

| Teste | O que verifica |
|---|---|
| `test_retorna_lista_vazia_sem_resultados` | Retorna `[]` quando Athena não encontra resultados |
| `test_retorna_registros_como_lista_de_dicts` | Converte corretamente rows do Athena em lista de dicts |
| `test_filtro_where_incluido_na_query` | WHERE inclui a cláusula gerada pelo LLM na query |
| `test_vote_count_fixo_sempre_presente` | Filtro fixo `vote_count >= 50` está sempre presente na query |
| `test_filtro_idioma_na_query` | WHERE inclui `original_language = 'ko'` para filtro de idioma |
| `test_filtro_duracao_na_query` | WHERE inclui `runtime_minutes <= 90` para filtro de duração |
| `test_filtro_temporadas_na_query` | WHERE inclui `number_of_seasons = 1` para filtro de temporadas |
| `test_filtro_em_cartaz_na_query` | WHERE inclui `in_theaters = true` para filtro de cinema |
| `test_filtro_plataforma_na_query` | WHERE inclui `lower(streaming_providers) LIKE '%netflix%'` para filtro de streaming |
| `test_filtro_faixa_de_ano_na_query` | WHERE inclui `year BETWEEN '2000' AND '2010'` para faixa de ano |
| `test_pool_maior_que_limite_solicitado_na_query` | LIMIT na query reflete o pool (`limit * _CANDIDATE_POOL_MULTIPLIER`), não o `limit` pedido |
| `test_limite_solicitado_e_limitado_a_15_antes_do_pool` | `limit=100` é capado a 15 antes de calcular o pool (`LIMIT 45` na query, não `LIMIT 100`/`LIMIT 15`) |
| `test_limite_minimo_e_1` | `limit=0` é capado a 1 antes de calcular o pool (`LIMIT 4` na query) |
| `test_pool_nao_ultrapassa_maximo_absoluto` | Pool nunca ultrapassa `_CANDIDATE_POOL_MAX` (45), mesmo quando `limit * _CANDIDATE_POOL_MULTIPLIER` seria maior |
| `test_amostra_e_limitada_ao_limit_solicitado_quando_pool_maior` | Pool com mais linhas que `limit` → resultado final tem exatamente `limit` títulos |
| `test_retorna_todos_quando_pool_nao_excede_limit` | Pool com menos linhas que `limit` → retorna todas, sem erro |
| `test_amostra_preserva_ordem_de_popularidade_do_subconjunto` | Mesmo com `random.sample` retornando índices fora de ordem, o resultado final preserva a ordem original (popularidade DESC) entre os títulos escolhidos |
| `test_rejeita_where_com_sql_perigoso` | Levanta `ValueError` quando a cláusula WHERE contém SQL perigoso |

### `TestRecommend` — Fluxo completo de recomendação

| Teste | O que verifica |
|---|---|
| `test_retorna_lista_vazia_se_athena_sem_resultados` | Retorna `[]` quando Athena não encontra resultados |
| `test_chama_llm_duas_vezes` | `litellm.completion` é chamado exatamente 2 vezes (etapa 1 + etapa 3) |
| `test_retorna_lista_de_titulos` | Resultado final é lista de dicts com campos corretos |
| `test_passa_filtros_extraidos_pelo_llm_para_athena` | `where_clause` e `limit` extraídos na etapa 1 são passados corretamente para `search_titles_spec()` |
| `test_retorna_lista_vazia_se_llm_nao_chama_tool` | Retorna `[]` sem chamar Athena quando o LLM não retorna `tool_calls` (ex: modelo não escolhe usar a tool) |
| `test_retorna_data_lancamento_formatada` | Campo `release_date` formatado pelo Python (ex: `"Maio de 1980"`) |
| `test_campos_formatados_pelo_python` | Valida que todos os campos determinísticos são formatados corretamente pelo Python (`type`, `year`, `genres`, `overview`, `rating`, `duration`, `streaming_providers`, `in_theaters`) |
| `test_motivo_incluido_no_resultado` | Campo `reason` da etapa 3 é mesclado corretamente ao registro formatado |
| `test_remove_markdown_code_block_do_motivo` | Remove cerca de código Markdown (` ```json ... ``` `) antes do `json.loads()` |
| `test_motivo_vazio_se_llm_retorna_string_vazia` | `reason=""` quando a etapa 3 retorna conteúdo vazio |
| `test_motivo_vazio_se_llm_retorna_json_invalido` | `reason=""` quando a etapa 3 retorna JSON inválido, sem levantar exceção |
| `test_motivo_funciona_com_id_como_string` | Merge por `id` funciona mesmo quando o LLM retorna `id` como string |
| `test_motivo_funciona_com_lista_direta_sem_wrapper` | Merge funciona com resposta em lista direta `[...]`, sem o wrapper `{"titles": [...]}` |
| `test_motivo_ignora_item_com_id_nao_conversivel` | Item com `id` que não converte para `int` (ex: `"abc"`) é ignorado no merge, sem levantar exceção |
| `test_payload_do_motivo_inclui_campos_de_ficha_tecnica` | Payload enviado à etapa 3 inclui `director`, `actor_names`, `keywords_pt` (além dos 6 campos mínimos) |
| `test_anexa_generos_destacados_ao_resultado` | `where_clause` com filtro de gênero → `highlighted_genres` populado e `highlighted_providers == []` no registro final |
| `test_anexa_provedores_destacados_ao_resultado` | `where_clause` com filtro de provedor → `highlighted_providers` populado e `highlighted_genres == []` no registro final |
| `test_destaque_vazio_sem_filtro_de_genero_ou_provedor` | `where_clause` sem filtro de gênero/provedor → ambas as chaves presentes como `[]` |

### `TestCacheWhere` — Cache de cláusulas WHERE

| Teste | O que verifica |
|---|---|
| `test_chave_cache_normaliza_entrada` | Chave do cache é idêntica para entradas com diferença de caixa/espaços |
| `test_salvar_e_buscar_cache` | Salvar e buscar retorna os mesmos argumentos |
| `test_cache_miss_retorna_none` | Retorna `None` para preferência não cacheada |
| `test_cache_expirado_retorna_none` | Retorna `None` e remove entrada quando TTL expira |
| `test_cache_evita_chamada_llm_passo_1` | Com cache preenchido, `litellm.completion` é chamado apenas 1 vez (etapa 3 — o motivo ainda roda, pois depende dos títulos reais retornados pelo Athena, não do cache da etapa 1) |
| `test_destaque_reproduzido_em_cache_hit` | Destaque de gênero/provedor extraído de uma `where_clause` cacheada é idêntico ao de uma chamada fresca com a mesma `where_clause` |

### `TestLogTokenUsage` — Logging de uso de tokens

| Teste | O que verifica |
|---|---|
| `test_loga_tokens_com_usage` | `logger.info` é chamado com `prompt_tokens`, `completion_tokens` e `step` no `extra` |
| `test_nao_loga_sem_usage` | `logger.info` não é chamado quando a resposta não possui atributo `usage` |
| `test_logger_tem_nivel_info_explicito` | `agent.logger.level` é `logging.INFO`, garantindo que os logs de tokens não sejam suprimidos quando `app.py` eleva o root logger para `ERROR` |

### `TestTranscribePreference` — Transcrição de áudio (Whisper via litellm)

Usa `_make_wav_bytes(duration_seconds)`, helper do próprio `test_agent.py` que gera um WAV de teste (silêncio) com a duração informada via módulo padrão `wave`. Qualquer falha é tratada pelo chamador (`app.py`).

| Teste | O que verifica |
|---|---|
| `test_transcreve_audio_com_sucesso` | Retorna o texto transcrito pelo mock de `litellm.transcription` |
| `test_remove_espacos_da_transcricao` | Remove espaços nas pontas do texto transcrito |
| `test_retorna_string_vazia_sem_fala_detectada` | Retorna `""` quando o provedor não detecta fala, sem levantar erro |
| `test_usa_modelo_e_idioma_configurados` | Chama `litellm.transcription` com `model=_TRANSCRIPTION_MODEL` e `language="pt"` |
| `test_propaga_erro_do_provedor` | Propaga `openai.APIError` (ou subclasse) quando a chamada ao provedor falha |
| `test_levanta_erro_sem_api_key_configurada` | Levanta `ValueError` quando `_TRANSCRIPTION_API_KEY` é `None` |
| `test_audio_dentro_do_limite_nao_levanta_erro` | Áudio com duração abaixo de `_MAX_AUDIO_SECONDS` chama `litellm.transcription` normalmente |
| `test_audio_muito_longo_levanta_erro_sem_chamar_api` | Áudio acima de `_MAX_AUDIO_SECONDS` levanta `AudioMuitoLongoError` **sem** chamar `litellm.transcription` (`assert_not_called()`), evitando gastar crédito à toa |

## Casos de teste — `test_componentes.py`

### `TestLoadAudioTimerScript` — Injeção do script do timer de áudio

| Teste | O que verifica |
|---|---|
| `test_injeta_script_via_components_html` | `components.html` é chamado com `height=0` e o script injetado contém o marcador `audio-timer-badge` (mock de `componentes.components.html`, já que não há `st.testing`/`AppTest` na suite) |
| `test_substitui_max_seconds_no_template` | O placeholder `__MAX_SECONDS__` é substituído pelo valor passado (`15` → `const maxSeconds = 15;`) — mesmo padrão de template string de `__MAX_CHARS__` em `contador_caracteres.js` |

### `TestRenderFeedback` — Renderização da caixa de mensagem de erro/aviso padronizada

| Teste | O que verifica |
|---|---|
| `test_renderiza_classe_error` | `kind="error"` gera `class="msg-error"` e ícone ❌ |
| `test_renderiza_classe_warning` | `kind="warning"` gera `class="msg-warning"` e ícone ⚠️ |
| `test_escapa_xss_na_mensagem` | `message` com `<script>` é escapado via `html.escape` |
| `test_extra_html_nao_e_escapado` | `extra_html` (ex: `<span id="countdown">`) passa intacto, sem escape — único uso hoje é o countdown de rate limit de busca |
| `test_sem_extra_html_nao_inclui_span` | Sem `extra_html`, nenhum `<span` aparece no HTML gerado |

### `TestLoadCountdownScript` — Injeção do script de countdown genérico (rate limit de busca, rate limit de transcrição e bloqueio de login)

| Teste | O que verifica |
|---|---|
| `test_injeta_script_via_components_html` | `components.html` é chamado com `height=0` e o script injetado contém o marcador `countdown` |
| `test_substitui_seconds_no_template` | O placeholder `__SECONDS__` é substituído pelo valor passado (`42` → `let remaining = 42;`) |
| `test_usa_countdown_como_element_id_padrao` | Sem `element_id` explícito, o script busca `getElementById("countdown")` |
| `test_substitui_element_id_customizado` | O placeholder `__ELEMENT_ID__` é substituído pelo `element_id` passado (ex: `"audio-countdown"`), necessário para não colidir com o `id="countdown"` do rate limit de busca quando os dois countdowns estão visíveis ao mesmo tempo |

### `TestLoadLoginButtonToggleScript` — Injeção do script de habilitar/desabilitar "Entrar" do login

| Teste | O que verifica |
|---|---|
| `test_injeta_script_via_components_html` | `components.html` é chamado com `height=0` e o script injetado contém o marcador `btn_entrar` |
| `test_substitui_locked_out_false` | O placeholder `__LOCKED_OUT__` é substituído por `false` quando `locked_out=False` |
| `test_substitui_locked_out_true` | O placeholder `__LOCKED_OUT__` é substituído por `true` quando `locked_out=True` |

### `TestPrioritize` — Reordenação de badges por termo destacado

| Teste | O que verifica |
|---|---|
| `test_sem_termos_retorna_lista_original` | Lista de termos vazia → `_prioritize` é no-op |
| `test_item_casado_vai_para_o_inicio` | Item que contém o termo destacado é movido para o início |
| `test_mantem_ordem_relativa_dentro_de_cada_grupo` | Múltiplos itens casados/não casados mantêm a ordem original entre si dentro de cada grupo |
| `test_case_insensitive` | Match funciona independente da caixa do termo/item |
| `test_termo_curto_bate_em_mais_de_um_genero` | Termo curto (ex: "ação") que é substring de mais de um gênero (ex: "Ação & Aventura" e "Animação") prioriza ambos |
| `test_termo_curto_bate_em_mais_de_um_provedor` | Mesmo cenário de overlap do lado de provedor (ex: termo "play" em "Google Play" e "Globoplay") |
| `test_lista_vazia_com_termos_nao_gera_erro` | Lista de items vazia com termos destacados presentes → `[]` sem erro |
| `test_key_extrai_nome_de_pares_provedor_logo` | Parâmetro `key` permite reordenar pares `(nome, logo_url)` comparando só o nome, preservando o par |

### `TestRenderProviderBadges` — Badges de provedor (logo com fallback texto)

| Teste | O que verifica |
|---|---|
| `test_com_logo_renderiza_img` | Provedor com logo renderiza `<img>` (alt = nome) em vez de texto |
| `test_sem_logo_cai_para_texto` | Provedor sem logo (string vazia) cai para badge de texto, igual ao comportamento anterior à feature |
| `test_logos_vazios_por_posicao_caem_para_texto_individualmente` | Em uma lista com múltiplos provedores, cada posição decide independentemente entre `<img>` e texto conforme tenha ou não logo |
| `test_logos_string_mais_curta_preenche_com_vazio` | Rede de segurança: `logos_raw` com menos posições que `names_raw` é completada com string vazia em vez de estourar índice |
| `test_escapa_html_no_nome_e_na_url_da_logo` | Nome e URL da logo passam por `html.escape` (proteção XSS) |
| `test_prioriza_provedor_destacado_mesmo_com_logo` | `highlighted` continua priorizando o provedor certo mesmo quando os badges são imagens, não texto |

### `TestRenderCard` — Renderização de cards individuais

| Teste | O que verifica |
|---|---|
| `test_card_basico_contem_titulo` | Card renderiza o título do filme |
| `test_card_ignora_tagline` | Card não renderiza tagline mesmo quando fornecida |
| `test_card_nao_exibe_elenco` | Card não renderiza nomes do elenco mesmo quando fornecidos |
| `test_card_nao_exibe_diretor` | Card não renderiza "Diretor: {nome}" mesmo quando fornecido |
| `test_card_com_certificacao` | Card exibe badge de classificação indicativa |
| `test_card_com_trailer` | Card exibe link clicável para o trailer, como item da linha de nota/data |
| `test_card_vitals_combina_nota_data_e_trailer` | Linha de vitals agrupa nota, data de lançamento e trailer, nessa ordem |
| `test_card_duracao_fica_em_linha_separada_apos_vitals` | Duração aparece em linha própria, depois da linha de nota/data/trailer |
| `test_card_vitals_omite_nota_ausente_sem_separador_solto` | Sem nota, a linha de vitals não deixa separador `·` solto |
| `test_card_sem_vitals_nao_gera_linha_vazia` | Sem nota, duração e data, nenhuma linha de vitals é gerada |
| `test_card_ignora_colecao` | Card não renderiza coleção/franquia mesmo quando fornecida |
| `test_card_ignora_criadores` | Card não renderiza criadores mesmo quando fornecidos |
| `test_card_ignora_redes_tv` | Card não renderiza redes de TV mesmo quando fornecidas |
| `test_card_sem_campos_opcionais_nao_gera_divs_vazias` | Campos opcionais ausentes não geram HTML vazio |
| `test_card_cinema_em_cartaz` | Card exibe "Em cartaz até DD/MM/YYYY" quando `in_theaters=True` |
| `test_card_nao_exibe_produtor` | Card não renderiza produtor mesmo quando fornecido |
| `test_card_nao_exibe_cinematografo` | Card não renderiza cinematógrafo mesmo quando fornecido |
| `test_card_nao_exibe_montador` | Card não renderiza montador mesmo quando fornecido |
| `test_card_com_streaming_providers` | Card exibe plataformas de streaming |
| `test_card_ignora_campo_de_logo_do_provedor` | Se `streaming_provider_logos`/`rent_buy_provider_logos` aparecerem no dict do card, são ignorados — nome do provedor renderiza só como texto, nunca `<img>` |
| `test_card_sem_rent_buy_providers_nao_exibe_bloco` | Sem `rent_buy_providers`, o bloco "Aluguel/Compra" não é renderizado |
| `test_card_com_rent_buy_providers_exibe_bloco` | Com `rent_buy_providers` preenchido, o bloco "Aluguel/Compra" aparece com os nomes das plataformas |
| `test_card_exibe_motivo` | Card exibe o motivo da recomendação (`reason`) |
| `test_card_escapa_xss` | Valores com `<script>` são escapados via `html.escape` |
| `test_card_escapa_xss_no_motivo` | Valor de `reason` com `<script>` é escapado via `html.escape` |
| `test_card_genero_destacado_entra_nos_visiveis_alem_do_limite` | Gênero destacado originalmente na 6ª posição (cairia no "+1") aparece nas 5 badges visíveis, e outro gênero passa a ficar no "+1" |
| `test_card_provedor_destacado_entra_nos_visiveis_alem_do_limite` | Mesmo cenário do teste acima, para provedores |
| `test_card_multiplos_generos_destacados_mantem_ordem_entre_si` | Dois gêneros destacados aparecem antes dos demais, mantendo ordem relativa entre si |
| `test_card_generos_e_provedores_destacados_priorizam_fileiras_independentes` | `highlighted_genres` e `highlighted_providers` populados juntos no mesmo card → cada fileira de badges prioriza os seus, independentemente uma da outra |
| `test_card_sem_chave_highlighted_ordem_permanece_igual` | Sem `highlighted_genres`/`highlighted_providers` no dict do título → ordem idêntica à anterior à feature (sem regressão) |
| `test_card_highlighted_vazio_ordem_permanece_igual` | `highlighted_genres`/`highlighted_providers` presentes mas vazios → ordem idêntica à anterior à feature |

### `TestRenderGrid` — Renderização do grid de cards

| Teste | O que verifica |
|---|---|
| `test_grid_vazio` | Grid vazio renderiza container sem cards |
| `test_grid_com_titulos` | Grid com múltiplos títulos renderiza múltiplos cards |

## Casos de teste — `test_formatacao.py`

### `TestFormatType` — Conversão de `media_type`

| Teste | O que verifica |
|---|---|
| `test_movie_para_filme` | `"movie"` → `"filme"` |
| `test_tv_para_serie` | `"tv"` → `"série"` |
| `test_valor_desconhecido` | Valor desconhecido retornado sem alteração |

### `TestFormatGenres` — Separação de gêneros

| Teste | O que verifica |
|---|---|
| `test_separa_por_virgula` | `"Terror, Drama"` → `["Terror", "Drama"]` |
| `test_retorna_lista_vazia_para_none` | `None` → `[]` |
| `test_retorna_lista_vazia_para_string_vazia` | `""` → `[]` |

### `TestFormatTitleDuration` — Formatação de duração

| Teste | O que verifica |
|---|---|
| `test_filme_com_duracao` | `146` min → `"2h 26min"` |
| `test_filme_sem_duracao` | `runtime_minutes=None` → `None` |
| `test_filme_menos_de_uma_hora` | `45` min → `"45min"` (sem horas) |
| `test_serie_completa` | Seasons + episodes + ep. runtime → `"3 temporadas · 36 eps · ~45 min/ep"` |
| `test_serie_sem_episode_runtime` | Omite parte de runtime → `"2 temporadas · 20 eps"` |
| `test_serie_uma_temporada` | Singular → `"1 temporada · 10 eps"` |
| `test_serie_sem_dados` | Todos os campos `None` → `None` |

### `TestFormatReleaseDate` — Formatação de data

| Teste | O que verifica |
|---|---|
| `test_data_valida` | `"1980-05-23"` → `"Maio de 1980"` |
| `test_data_none` | `None` → `None` |
| `test_data_vazia` | `""` → `None` |
| `test_data_curta` | `"1980"` (sem mês) → `None` |

### `TestFormatTheaterEndDate` — Formatação de data de saída do cinema

| Teste | O que verifica |
|---|---|
| `test_em_cartaz_com_data` | `"2025-07-15"` + `in_theaters=True` → `"15/07/2025"` |
| `test_fora_de_cartaz` | `in_theaters=False` → `None` |
| `test_em_cartaz_sem_data` | `theater_end_date=None` → `None` |

### `TestFormatRating` — Conversão de nota

| Teste | O que verifica |
|---|---|
| `test_float_valido` | `8.4` → `8.4` |
| `test_string_valida` | `"7.5"` → `7.5` |
| `test_none` | `None` → `None` |
| `test_string_vazia` | `""` → `None` |

### `TestFormatRecord` — Formatação completa de um registro

| Teste | O que verifica |
|---|---|
| `test_registro_completo_filme` | Registro de filme formatado com todos os campos corretos |
| `test_novos_campos_filme` | Campos `writers`, `composer`, `keywords` (pt) formatados corretamente |
| `test_novos_campos_crew_e_extras` | Campos `producer`, `cinematographer`, `editor`, `production_countries`, `rent_buy_providers`, `recommended`, `similar`, `alternative_titles` formatados corretamente |
| `test_novos_campos_nulos` | Campos `writers`, `composer`, `rent_buy_providers` (entre outros) retornam `None` quando ausentes |
| `test_registro_serie` | Registro de série com `type="série"` e duração formatada com temporadas |

## Como executar

```bash
# Apenas os testes do lightsail
pytest test/lightsail_ia/ -v

# Com cobertura
pytest test/lightsail_ia/ --cov=app/lightsail_ia --cov-report=term-missing
```

## Cobertura mínima

**95%** — definido via `--cov-fail-under=95` no workflow de CI (`.github/workflows/01_test.yml`). `app.py` está formalmente excluído dessa medição via `omit=` no `.coveragerc` (ver seção abaixo) — não conta nem a favor nem contra o gate.

## Observação sobre testes de interface

A interface Streamlit (`app.py`) não é coberta por testes automatizados nesta suite — e por isso está listada em `omit=` no `.coveragerc`, no mesmo mecanismo usado para excluir `test/*`/`infra/*` do gate. Sem essa exclusão, o arquivo ficaria em 0% de cobertura (roda código a nível de import, sem framework tipo `st.testing.v1.AppTest` no projeto) e derrubaria o gate de 95% sozinho. Para validar o app visualmente, execute localmente:

```bash
cd app/lightsail_ia
streamlit run app.py
```

A variável `CLOUDWATCH_LOG_GROUP` não é definida no conftest — isso é intencional: sem ela, o handler watchtower não é ativado e os testes rodam sem dependência do CloudWatch.

