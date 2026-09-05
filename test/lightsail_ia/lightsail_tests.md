# Testes — lightsail_ia

## O que é testado

Testa as funções do agente de recomendação (`app/lightsail_ia/agent.py`), as funções de formatação (`app/lightsail_ia/formatting.py`), os componentes de renderização HTML (`app/lightsail_ia/components.py`) e o bootstrap de processo/rate limiting (`app/lightsail_ia/infrastructure.py`). O `test_agent.py` cobre `recommend()`, `search_titles_spec()`, validação SQL, extração de termos de gênero/provedor para destaque nas badges, cache e logging de tokens. O `test_formatting.py` cobre as funções puras de formatação (`format_record`, `_format_type`, `_format_genres`, `_format_title_duration`, `_format_release_date`, `_format_theater_end_date`, `_format_rating`). O `test_components.py` cobre a renderização de cards e grids (`render_card`, `render_grid`), a priorização de badges por termo destacado (`_prioritize`), a caixa de mensagem de feedback padronizada (`render_feedback`), os rodapés (`render_footer`/`render_form_footer`, incluindo o link de contato por e-mail via `_render_contact_line()`), o helper de ícone Lucide (`icon()`/`ICON_PATHS`) e a injeção dos scripts `load_audio_timer_script`/`load_countdown_script`/`load_form_button_toggle_script`, incluindo escape XSS e verificação de campos exibidos/ignorados. O `test_infrastructure.py` cobre os ramos de saída antecipada de `load_filmbot_password`/`setup_cloudwatch_logging` (sem tocar AWS de verdade), as funções puras de rate limiting (`get_client_ip`, `events_in_window`, `seconds_until_available`) e as chamadas Cognito/SNS da autenticação e do perfil (`sign_up`, `confirm_sign_up`, `resend_confirmation_code`, `authenticate`, `record_login`, `record_password_update`, `is_admin`, `get_user_status`, `get_user_profile`, `update_user_name`, `change_password`, `request_password_reset`, `confirm_password_reset`, `list_pending_users`, `list_active_users`, `list_unconfirmed_users`, `approve_signup`, `reject_signup`, `revoke_access`, `add_to_admins_group`, `notify_new_signup`) — todas mockando `boto3.client` diretamente, mesmo padrão já usado pelo resto do arquivo, sem `moto`. Os testes usam estilo **pytest** (classes simples, `assert` nativo, `with patch(...)` como context manager). A interface Streamlit (`app.py`, `forms.py`, `admin.py`, `profile.py`, `recommendation.py`, `cards.py`) não é testada diretamente — é validada via execução manual. Todas as chamadas externas (LLM e Athena) são substituídas por **mocks** via `unittest.mock` — objetos falsos que simulam respostas do LLM e do banco de dados sem fazer chamadas reais, evitando custos de API e tornando os testes determinísticos.

## Estrutura

```
test/lightsail_ia/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_agent.py             # Testes do agente (LLM, Athena, cache, validação)
├── test_components.py       # Testes de renderização HTML (cards e grids)
├── test_formatting.py        # Testes das funções puras de formatação
└── test_infrastructure.py    # Testes do bootstrap de processo e rate limiting
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
| `COGNITO_USER_POOL_ID` | `"sa-east-1_testpool"` |
| `COGNITO_APP_CLIENT_ID` | `"test-app-client-id"` |
| `SNS_NEW_SIGNUP_TOPIC_ARN` | `"arn:aws:sns:sa-east-1:123456789012:test-new-signup-topic"` |

| Fixture | Escopo | Descrição |
|---|---|---|
| `_limpar_cache_where` | `autouse` | Limpa `agent._WHERE_CACHE` antes de cada teste para garantir isolamento entre testes |

## Funções auxiliares de mock (`test_agent.py`)

| Função | Descrição |
|---|---|
| `_setup_athena_mock(mock_boto3, rows_data)` | Configura o mock do `boto3` para simular as 3 etapas da API nativa do Athena: `start_query_execution` → `get_query_execution` (polling) → `get_paginator().paginate()`. `rows_data` define as linhas de resultado; `None` retorna apenas o header (resultado vazio). |
| `_mock_litellm(tool_args, reason_content=None)` | Retorna lista com 2 respostas para `side_effect` de `litellm.completion`: Etapa 1 (Function Calling com `tool_args`) e Etapa 3 (motivo, com o conteúdo de `reason_content` — ou `{"titles": []}` por padrão, se `None`). Inclui mock de `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`) para compatibilidade com `_log_token_usage()`. |

## Casos de teste — `test_agent.py`

### `TestTool` — Descrição da tool `search_titles_spec` exposta ao LLM

| Teste | O que verifica |
|---|---|
| `test_descricao_do_limit_orienta_quantidade_padrao_entre_6_e_9` | Descrição do parâmetro `limit` menciona "6", "9" (quantidade padrão orientada ao LLM) e "15" (teto) |

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
| `test_select_inclui_title_status` | SELECT inclui `title_status` — usado como fallback da `cinema-row` no card quando não está em cartaz, não tem próximo episódio nem é lançamento futuro |
| `test_filtro_where_incluido_na_query` | WHERE inclui a cláusula gerada pelo LLM na query |
| `test_vote_count_fixo_sempre_presente` | Filtro fixo `vote_count >= 50` está sempre presente na query |
| `test_titulo_futuro_ignora_vote_count` | WHERE inclui `(vote_count >= 50 OR air_date > CAST(CURRENT_DATE AS VARCHAR))` — título com `air_date` futuro passa sem exigir voto |
| `test_filtro_idioma_na_query` | WHERE inclui `original_language = 'ko'` para filtro de idioma |
| `test_filtro_duracao_na_query` | WHERE inclui `runtime_minutes <= 90` para filtro de duração |
| `test_filtro_temporadas_na_query` | WHERE inclui `number_of_seasons = 1` para filtro de temporadas |
| `test_filtro_em_cartaz_na_query` | WHERE inclui `in_theaters = true` para filtro de cinema |
| `test_filtro_plataforma_na_query` | WHERE inclui `lower(streaming_providers) LIKE '%netflix%'` para filtro de streaming |
| `test_filtro_faixa_de_ano_na_query` | WHERE inclui `year BETWEEN '2000' AND '2010'` para faixa de ano |
| `test_pool_maior_que_limite_solicitado_na_query` | LIMIT na query reflete o pool (`limit * _CANDIDATE_POOL_MULTIPLIER`), não o `limit` pedido |
| `test_limite_padrao_fica_entre_6_e_9` | Sem passar `limit`, o pool gerado reflete `_DEFAULT_RECOMMENDATION_COUNT` (valor entre 6 e 9) em vez do antigo padrão de 15 |
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
| `test_passos_1_e_3_usam_retry_configurado` | As duas chamadas `litellm.completion` (etapas 1 e 3) recebem `num_retries=_LLM_NUM_RETRIES` |
| `test_passos_1_e_3_usam_timeout_e_max_tokens_configurados` | As duas chamadas recebem `timeout`/`max_tokens` específicos por etapa (`_LLM_TIMEOUT_STEP1_SECONDS`/`_LLM_MAX_TOKENS_STEP1` na etapa 1, `_LLM_TIMEOUT_STEP3_SECONDS`/`_LLM_MAX_TOKENS_STEP3` na etapa 3), sem perder o `num_retries` já configurado |
| `test_retorna_lista_vazia_se_llm_nao_chama_tool` | Retorna `[]` sem chamar Athena quando o LLM não retorna `tool_calls` (ex: modelo não escolhe usar a tool) |
| `test_retorna_data_lancamento_formatada` | Campo `release_date` formatado pelo Python (ex: `"Mai de 1980"`) |
| `test_campos_formatados_pelo_python` | Valida que todos os campos determinísticos são formatados corretamente pelo Python (`type`, `year`, `genres`, `overview`, `rating`, `duration`, `streaming_providers`, `in_theaters`) |
| `test_motivo_incluido_no_resultado` | Campo `reason` da etapa 3 é mesclado corretamente ao registro formatado |
| `test_remove_markdown_code_block_do_motivo` | Remove cerca de código Markdown (` ```json ... ``` `) antes do `json.loads()` |
| `test_motivo_vazio_se_llm_retorna_string_vazia` | `reason=""` quando a etapa 3 retorna conteúdo vazio |
| `test_motivo_vazio_se_llm_retorna_json_invalido` | `reason=""` quando a etapa 3 retorna JSON inválido, sem levantar exceção |
| `test_motivo_funciona_com_id_como_string` | Merge por `id` funciona mesmo quando o LLM retorna `id` como string |
| `test_motivo_funciona_com_lista_direta_sem_wrapper` | Merge funciona com resposta em lista direta `[...]`, sem o wrapper `{"titles": [...]}` |
| `test_motivo_ignora_item_com_id_nao_conversivel` | Item com `id` que não converte para `int` (ex: `"abc"`) é ignorado no merge, sem levantar exceção |
| `test_payload_do_motivo_inclui_campos_de_ficha_tecnica` | Payload enviado à etapa 3 inclui `director`, `actor_names`, `keywords_pt` (além dos 6 campos mínimos) |
| `test_overview_e_truncada_no_payload_do_motivo` | `overview` com mais de `_MAX_OVERVIEW_CHARS_FOR_LLM` caracteres é truncada antes de entrar no payload da etapa 3 |
| `test_overview_ausente_nao_quebra_o_truncamento` | `overview=None` (registro sem sinopse) não levanta exceção ao truncar |
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
| `test_logger_tem_nivel_info_explicito` | `agent.logger.level` é `logging.INFO`, garantindo que os logs de tokens não sejam suprimidos quando `infrastructure.py` eleva o root logger para `ERROR` |

### `TestLogStepLatency` — Logging de latência por passo

| Teste | O que verifica |
|---|---|
| `test_loga_step_e_tempo_decorrido` | `_log_step_latency(step, elapsed_seconds)` chama `logger.info` com `step` e `elapsed_seconds` (arredondado a 3 casas) no `extra` |

### `TestRecommendLogaLatenciaPorPasso` — Integração: `recommend()` chama `_log_step_latency` para cada etapa

| Teste | O que verifica |
|---|---|
| `test_loga_latencia_dos_3_passos_em_cache_miss` | Em cache miss da etapa 1, `_log_step_latency` é chamado 3 vezes, nesta ordem: `step1_where`, `step2_athena`, `step3_reasons` |
| `test_loga_apenas_step2_e_step3_em_cache_hit` | Em cache hit da etapa 1 (cláusula WHERE já cacheada), `_log_step_latency` é chamado só para `step2_athena` e `step3_reasons` — a etapa 1 é pulada e não gera log de latência |

### `TestTranscribePreference` — Transcrição de áudio (Whisper via litellm)

Usa `_make_wav_bytes(duration_seconds)`, helper do próprio `test_agent.py` que gera um WAV de teste (silêncio) com a duração informada via módulo padrão `wave`. Qualquer falha é tratada pelo chamador (`recommendation.py`).

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

## Casos de teste — `test_components.py`

### `TestLoadAudioTimerScript` — Injeção do script do timer de áudio

| Teste | O que verifica |
|---|---|
| `test_injeta_script_via_components_html` | `components.html` é chamado com `height=0` e o script injetado contém o marcador `audio-timer-badge` (mock de `components.components.html`, já que não há `st.testing`/`AppTest` na suite) |
| `test_substitui_max_seconds_no_template` | O placeholder `__MAX_SECONDS__` é substituído pelo valor passado (`15` → `const maxSeconds = 15;`) — mesmo padrão de template string de `__MAX_CHARS__` em `contador_caracteres.js` |

### `TestLoadScrollLockScript` — Injeção do script que neutraliza o `scrollLeft` fantasma de `stMain`/`stAppViewContainer`

| Teste | O que verifica |
|---|---|
| `test_injeta_script_via_components_html` | `components.html` é chamado com `height=0` e o script injetado contém o marcador `scrollLeft` |

### `TestRenderFeedback` — Renderização da caixa de mensagem de erro/aviso padronizada

| Teste | O que verifica |
|---|---|
| `test_renderiza_classe_error` | `kind="error"` gera `class="msg-error"` e ícone ❌ |
| `test_renderiza_classe_warning` | `kind="warning"` gera `class="msg-warning"` e ícone ⚠️ |
| `test_renderiza_classe_success` | `kind="success"` gera `class="msg-success"` e ícone ✅ (usado pela tela "cadastro enviado" de `forms.py`) |
| `test_escapa_xss_na_mensagem` | `message` com `<script>` é escapado via `html.escape` |
| `test_extra_html_nao_e_escapado` | `extra_html` (ex: `<span id="countdown">`) passa intacto, sem escape — único uso hoje é o countdown de rate limit de busca |
| `test_sem_extra_html_nao_inclui_span_de_countdown` | Sem `extra_html`, nenhum `<span id="countdown">` aparece no HTML gerado |
| `test_separa_icone_e_texto_em_spans_proprios` | Ícone e mensagem vêm em `<span class="msg-icon">`/`<span class="msg-text">` separados — permite ao CSS alinhar os dois verticalmente via flexbox |

### `TestLoadCountdownScript` — Injeção do script de countdown genérico (rate limit de busca, rate limit de transcrição, bloqueio de login e cooldown de reenviar código)

| Teste | O que verifica |
|---|---|
| `test_injeta_script_via_components_html` | `components.html` é chamado com `height=0` e o script injetado contém o marcador `countdown` |
| `test_substitui_seconds_no_template` | O placeholder `__SECONDS__` é substituído pelo valor passado (`42` → `let remaining = 42;`) |
| `test_usa_countdown_como_element_id_padrao` | Sem `element_id` explícito, o script busca `getElementById("countdown")` |
| `test_substitui_element_id_customizado` | O placeholder `__ELEMENT_ID__` é substituído pelo `element_id` passado (ex: `"audio-countdown"`), necessário para não colidir com o `id="countdown"` do rate limit de busca quando os dois countdowns estão visíveis ao mesmo tempo |

### `TestLoadFormButtonToggleScript` — Injeção do script de habilitar/desabilitar o botão de submit das telas de autenticação

| Teste | O que verifica |
|---|---|
| `test_injeta_script_via_components_html` | `components.html` é chamado com `height=0` e o script injetado contém o marcador `btn_entrar` (`button_key` padrão) |
| `test_substitui_locked_out_false` | O placeholder `__LOCKED_OUT__` é substituído por `false` quando `locked_out=False` |
| `test_substitui_locked_out_true` | O placeholder `__LOCKED_OUT__` é substituído por `true` quando `locked_out=True` |
| `test_substitui_button_key_customizado` | O placeholder `__BUTTON_KEY__` é substituído pelo `button_key` passado (ex: `"btn_cadastrar"`) — usado pelas telas de cadastro/esqueci senha, que reaproveitam o mesmo script com um botão diferente de `btn_entrar` |

### `TestLoadPasswordRequirementsGateScript` — Injeção do script de requisitos de senha dinâmicos (cadastro e redefinir senha)

| Teste | O que verifica |
|---|---|
| `test_injeta_script_via_components_html` | `components.html` é chamado com `height=0` e o script injetado contém o `password_key` passado |
| `test_substitui_password_key_confirm_key_e_button_key` | Os placeholders `__PASSWORD_KEY__`/`__CONFIRM_KEY__`/`__BUTTON_KEY__` são substituídos pelos valores passados |
| `test_email_key_default_vazio` | Sem `email_key` explícito, o script recebe `emailKey = ""` (tela de redefinir senha, sem campo de e-mail) |
| `test_substitui_email_key_customizado` | O placeholder `__EMAIL_KEY__` é substituído pelo `email_key` passado (ex: `"signup_email"`) |
| `test_locked_out_default_false` | Sem `locked_out` explícito, o placeholder `__LOCKED_OUT__` é substituído por `false` |
| `test_substitui_locked_out_true` | O placeholder `__LOCKED_OUT__` é substituído por `true` quando `locked_out=True` — usado pelo bloqueio de tentativas de código incorreto na redefinição de senha (`forms.py::_render_forgot_password_confirm`), pra impedir o script de reabilitar o botão via digitação enquanto o backend mantém `disabled=True` |

### `TestMatchesHighlighted` — Predicado de match compartilhado por `_prioritize`/render de badges

| Teste | O que verifica |
|---|---|
| `test_sem_termos_retorna_falso` | Lista de termos vazia → `False` |
| `test_item_bate_com_termo` | Item que contém o termo → `True` |
| `test_item_nao_bate_com_termo` | Item que não contém nenhum termo → `False` |
| `test_case_insensitive` | Match funciona independente da caixa do termo/item |

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
| `test_provedor_destacado_ganha_classe_highlighted` | Provedor destacado renderiza com a classe `.highlighted` (borda + texto laranja); os demais renderizam sem ela |

### `TestIcon` — Ícone Lucide inline (`icon()`/`ICON_PATHS`)

| Teste | O que verifica |
|---|---|
| `test_icone_mic_existe` | Ícone "mic" existe em `ICON_PATHS` e monta `<svg>` com a classe `icon-mic` — usado só em `recommendation.py`, sem cobertura indireta via `render_card()` |
| `test_icone_usa_stroke_current_color` | `icon()` sempre usa `stroke="currentColor"` (cor herdada via CSS) |
| `test_icone_respeita_size_customizado` | Parâmetro `size` reflete em `width`/`height` do `<svg>` |
| `test_icone_user_existe` | Ícone "user" existe em `ICON_PATHS` — usado só no menu vertical de `profile.py`/`admin.py`, fora do gate de cobertura |
| `test_icone_lock_existe` | Ícone "lock" existe em `ICON_PATHS` — mesmo caso do "user" acima |
| `test_icone_mail_existe` | Ícone "mail" existe em `ICON_PATHS` e monta `<svg>` com a classe `icon-mail` — usado por `_render_contact_line()` no rodapé |

### `TestRenderCard` — Renderização de cards individuais

| Teste | O que verifica |
|---|---|
| `test_card_basico_contem_titulo` | Card renderiza o título do filme |
| `test_card_ignora_tagline` | Card não renderiza tagline mesmo quando fornecida |
| `test_card_nao_exibe_elenco` | Card não renderiza nomes do elenco mesmo quando fornecidos |
| `test_card_nao_exibe_diretor` | Card não renderiza "Diretor: {nome}" mesmo quando fornecido |
| `test_card_com_certificacao` | Card exibe badge de classificação indicativa |
| `test_card_com_trailer` | Card exibe link clicável para o trailer |
| `test_card_vitals_combina_nota_data_e_trailer` | Linha de vitals agrupa nota, data de lançamento e trailer, nessa ordem |
| `test_card_duracao_fica_em_linha_separada_apos_vitals` | Duração aparece em linha própria, depois da linha de nota/data/trailer |
| `test_card_vitals_omite_nota_ausente_sem_separador_solto` | Sem nota, a linha de vitals não deixa separador `·` solto |
| `test_card_sem_vitals_nao_gera_linha_vazia` | Sem nota, duração e data, nenhuma linha de vitals é gerada |
| `test_card_ignora_colecao` | Card não renderiza coleção/franquia mesmo quando fornecida |
| `test_card_ignora_criadores` | Card não renderiza criadores mesmo quando fornecidos |
| `test_card_ignora_redes_tv` | Card não renderiza redes de TV mesmo quando fornecidas |
| `test_card_sem_campos_opcionais_nao_gera_divs_vazias` | Campos opcionais ausentes não geram HTML vazio |
| `test_card_cinema_em_cartaz` | Card exibe "Em cartaz até DD/MM/YYYY" quando `in_theaters=True` |
| `test_card_status_fallback_filme_ja_lancado` | Sem `in_theaters`/próximo episódio/`upcoming_date`, a `cinema-row` cai no 4º ramo e exibe `title_status` puro (ex: "Lançado") — inclusive no caso comum de filme já lançado e fora de cartaz |
| `test_card_status_fallback_serie_encerrada` | Série com `title_status="Encerrada"` (sem os 3 badges anteriores) exibe "Encerrada" na `cinema-row` — informa que não haverá mais episódios |
| `test_card_em_cartaz_tem_prioridade_sobre_status` / `test_card_proximo_episodio_tem_prioridade_sobre_status` / `test_card_em_breve_tem_prioridade_sobre_status` | `title_status` nunca aparece quando um dos 3 estados anteriores (em cartaz, próximo episódio, em breve) está presente — confirma a ordem de prioridade em cartaz > próximo episódio > em breve > status |
| `test_card_nao_exibe_produtor` | Card não renderiza produtor mesmo quando fornecido |
| `test_card_nao_exibe_cinematografo` | Card não renderiza cinematógrafo mesmo quando fornecido |
| `test_card_nao_exibe_montador` | Card não renderiza montador mesmo quando fornecido |
| `test_card_com_streaming_providers` | Card exibe plataformas de streaming |
| `test_card_ignora_campo_de_logo_do_provedor` | Se `streaming_provider_logos`/`rent_buy_provider_logos` aparecerem no dict do card, são ignorados — nome do provedor renderiza só como texto, nunca `<img>` |
| `test_card_sem_rent_buy_providers_nao_exibe_bloco` | Sem `rent_buy_providers`, o bloco "Aluguel/Compra" não é renderizado |
| `test_card_com_rent_buy_providers_exibe_bloco` | Com `rent_buy_providers` preenchido, o bloco "Aluguel/Compra" aparece com os nomes das plataformas |
| `test_card_exibe_motivo` | Card exibe o motivo da recomendação (`reason`) |
| `test_card_motivo_string_vazia_gera_texto_de_fallback` | `reason=""` (Passo 3 rodou mas não gerou motivo pra este título) exibe `_REASON_FALLBACK_TEXT` em vez de omitir a seção |
| `test_card_motivo_string_vazia_mantem_rotulo_insight_do_filmbot` | Com `reason=""`, o rótulo "💡 Insight do FilmBot" continua aparecendo junto do texto de fallback |
| `test_card_escapa_xss` | Valores com `<script>` são escapados via `html.escape` |
| `test_card_escapa_xss_no_motivo` | Valor de `reason` com `<script>` é escapado via `html.escape` |
| `test_card_genero_destacado_entra_nos_visiveis_alem_do_limite` | Gênero destacado originalmente na 6ª posição (cairia no "+1") aparece nas 5 badges visíveis, e outro gênero passa a ficar no "+1" |
| `test_card_provedor_destacado_entra_nos_visiveis_alem_do_limite` | Mesmo cenário do teste acima, para provedores |
| `test_card_multiplos_generos_destacados_mantem_ordem_entre_si` | Dois gêneros destacados aparecem antes dos demais, mantendo ordem relativa entre si |
| `test_card_genero_destacado_ganha_classe_highlighted_e_nao_destacado_nao_ganha` | Gênero destacado renderiza com a classe `.highlighted`; gênero não destacado no mesmo card renderiza sem ela |
| `test_card_provedor_destacado_ganha_classe_highlighted_e_nao_destacado_nao_ganha` | Mesmo cenário do teste acima, para provedores |
| `test_card_multiplos_generos_destacados_ganham_highlighted_todos` | Dois gêneros destacados no mesmo card (`highlighted_genres` com 2 termos) ganham `.highlighted` cada um, não só o primeiro |
| `test_card_generos_e_provedores_destacados_priorizam_fileiras_independentes` | `highlighted_genres` e `highlighted_providers` populados juntos no mesmo card → cada fileira de badges prioriza os seus, independentemente uma da outra |
| `test_card_sem_chave_highlighted_ordem_permanece_igual` | Sem `highlighted_genres`/`highlighted_providers` no dict do título → ordem idêntica à anterior à feature (sem regressão) |
| `test_card_highlighted_vazio_ordem_permanece_igual` | `highlighted_genres`/`highlighted_providers` presentes mas vazios → ordem idêntica à anterior à feature |

### `TestRenderGrid` — Renderização do grid de cards

| Teste | O que verifica |
|---|---|
| `test_grid_vazio` | Grid vazio renderiza container sem cards |
| `test_grid_com_titulos` | Grid com múltiplos títulos renderiza múltiplos cards |

### `TestRenderFooter` — Rodapé da página principal

| Teste | O que verifica |
|---|---|
| `test_mantem_credito_tmdb` | Regressão: rodapé continua exibindo o crédito "TMDB" após a adição do contato |
| `test_inclui_link_de_contato_por_email` | Rodapé inclui `<a href="mailto:filmbot.lsgalvao@gmail.com">` com o ícone "mail" (`_render_contact_line()`) |

### `TestRenderFormFooter` — Rodapé simplificado das telas de login/cadastro

| Teste | O que verifica |
|---|---|
| `test_inclui_link_de_contato_por_email` | Rodapé de login também inclui o mesmo link de contato por e-mail (`_render_contact_line()`) |

### `TestValidatePassword` — Política de senha (movida de `forms.py`, também usada por `profile.py`)

| Teste | O que verifica |
|---|---|
| `test_aceita_senha_que_atende_todos_os_criterios` | Senha válida → `""` |
| `test_rejeita_senha_curta_demais` | Menos de 8 caracteres → mensagem citando "8 caracteres" |
| `test_rejeita_senha_longa_demais` | Mais de 16 caracteres → mensagem citando "16 caracteres" |
| `test_rejeita_senha_sem_letra_minuscula` | Sem minúscula → mensagem citando "minúscula" |
| `test_rejeita_senha_sem_letra_maiuscula` | Sem maiúscula → mensagem citando "maiúscula" |
| `test_rejeita_senha_sem_numero` | Sem número → mensagem citando "número" |
| `test_rejeita_senha_sem_simbolo` | Sem símbolo → mensagem citando "símbolo" |

## Casos de teste — `test_formatting.py`

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
| `test_filme_com_duracao` | `146` min (≥ 1h) → `"2h 26min (146min)"` (parêntese com o total em minutos) |
| `test_filme_sem_duracao` | `runtime_minutes=None` → `None` |
| `test_filme_menos_de_uma_hora` | `45` min → `"45min"` (sem horas, sem parêntese — seria redundante) |
| `test_serie_completa` | Seasons + episodes + ep. runtime → `"3 temp · 36 ep · ~45 min/ep"` (tudo abreviado) |
| `test_serie_sem_episode_runtime` | Omite parte de runtime → `"2 temp · 20 ep"` |
| `test_serie_uma_temporada_um_episodio` | Quantidade 1 não muda a abreviação (sem plural) → `"1 temp · 1 ep"` |
| `test_serie_sem_dados` | Todos os campos `None` → `None` |

### `TestFormatReleaseDate` — Formatação de data

| Teste | O que verifica |
|---|---|
| `test_data_valida` | `"1980-05-23"` → `"Mai de 1980"` (mês abreviado) |
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
| `test_novos_campos_filme` | Campos `writers`, `composer`, `keywords` (pt), `title_status` formatados corretamente |
| `test_novos_campos_crew_e_extras` | Campos `producer`, `cinematographer`, `editor`, `production_countries`, `rent_buy_providers`, `recommended`, `similar`, `alternative_titles` formatados corretamente |
| `test_novos_campos_nulos` | Campos `writers`, `composer`, `rent_buy_providers`, `title_status` (entre outros) retornam `None` quando ausentes — `title_status` ausente representa um título ainda não enriquecido pelo `glue_details` |
| `test_registro_serie` | Registro de série com `type="Série"` e duração formatada abreviada (`temp`/`ep`) |

## Casos de teste — `test_infrastructure.py`

### `TestLoadFilmbotPassword` — Bootstrap da senha via Secrets Manager

| Teste | O que verifica |
|---|---|
| `test_retorna_sem_chamar_secrets_manager_quando_secret_arn_nao_configurado` | Sem `FILMBOT_SECRET_ARN`, retorna sem chamar `boto3.client` |
| `test_retorna_sem_chamar_secrets_manager_quando_secrets_toml_ja_existe` | Com `secrets.toml` já existente (mockado), retorna sem chamar `boto3.client` |

### `TestSetupCloudwatchLogging` — Bootstrap do logging CloudWatch

| Teste | O que verifica |
|---|---|
| `test_retorna_sem_registrar_handler_quando_log_group_nao_configurado` | Sem `CLOUDWATCH_LOG_GROUP`, retorna sem instanciar `watchtower.CloudWatchLogHandler` |

Só o ramo de saída antecipada é testado — o ramo que efetivamente chama AWS (criação do handler, cliente `boto3.client("logs")`) fica sem teste, mesmo padrão já tolerado hoje para o ramo AWS de `agent.py::_load_llm_api_key()`.

### `TestGetClientIp` — Extração do IP do cliente

| Teste | O que verifica |
|---|---|
| `test_retorna_local_quando_nao_ha_header_x_forwarded_for` | Fora de um request real (sem header `X-Forwarded-For`), retorna `"local"` |

### `TestEventsInWindow` / `TestSecondsUntilAvailable` — Rate limiting por janela deslizante

| Teste | O que verifica |
|---|---|
| `test_conta_apenas_eventos_dentro_da_janela` | Eventos fora da janela não entram na contagem |
| `test_limpa_eventos_expirados_do_historico` | Eventos expirados são removidos do dict de histórico (mutação in-place) |
| `test_retorna_zero_para_ip_sem_historico` | IP sem histórico prévio → `0` |
| `test_retorna_zero_quando_nao_ha_historico` | Sem histórico, `seconds_until_available` retorna `0` |
| `test_calcula_segundos_restantes_ate_evento_mais_antigo_expirar` | Calcula corretamente os segundos restantes até o evento mais antigo sair da janela |
| `test_retorna_zero_quando_janela_ja_expirou` | Janela já expirada → `0`, nunca negativo |

### Autenticação e perfil (Cognito/SNS) — `TestSignUp`, `TestConfirmSignUp`, `TestResendConfirmationCode`, `TestAuthenticate`, `TestRecordLogin`, `TestRecordPasswordUpdate`, `TestGetUserProfile`, `TestUpdateUserName`, `TestChangePassword`, `TestIsAdmin`, `TestGetUserStatus`, `TestRequestPasswordReset`, `TestConfirmPasswordReset`, `TestListPendingUsers`, `TestListActiveUsers`, `TestListUnconfirmedUsers`, `TestApproveSignup`, `TestRejectSignup`, `TestRevokeAccess`, `TestAddToAdminsGroup`, `TestNotifyNewSignup`

Todas mockam `src.infrastructure.boto3.client` e verificam a chamada exata à API do Cognito/SNS (`assert_called_once_with`), sem tocar AWS de verdade — mesmo padrão do resto do arquivo.

| Teste | O que verifica |
|---|---|
| `test_chama_sign_up_com_email_senha_e_nome` | `sign_up()` chama `SignUp` com `ClientId`/`Username`/`Password`/`UserAttributes` (email + name) corretos |
| `test_nao_desabilita_a_conta_no_signup` | `sign_up()` **não** chama `AdminDisableUser` — testado empiricamente que `ConfirmSignUp` rejeita qualquer código (mesmo o certo) com `CodeMismatchException` quando a conta já está `Disabled` |
| `test_chama_confirm_sign_up_com_email_e_codigo` (`TestConfirmSignUp`) | `confirm_sign_up()` chama `ConfirmSignUp` com `ClientId`/`Username`/`ConfirmationCode` |
| `test_desabilita_a_conta_depois_de_confirmar` | `confirm_sign_up()` também chama `AdminDisableUser`, só depois do `ConfirmSignUp` ter sucesso |
| `test_nao_desabilita_a_conta_quando_confirm_sign_up_falha` | Se `ConfirmSignUp` falhar (`ClientError`), `AdminDisableUser` não é chamado e a exceção propaga |
| `test_chama_resend_confirmation_code_com_email` (`TestResendConfirmationCode`) | `resend_confirmation_code()` chama `ResendConfirmationCode` com `ClientId`/`Username` |
| `test_retorna_ok_quando_credenciais_corretas` | `authenticate()` chama `AdminInitiateAuth` (`ADMIN_USER_PASSWORD_AUTH`) e retorna `"ok"` |
| `test_retorna_pending_quando_cadastro_ainda_nao_aprovado` | `ClientError(UserNotConfirmedException)` → retorna `"pending"` |
| `test_retorna_invalid_para_credenciais_incorretas_ou_usuario_inexistente` | Parametrizado: `NotAuthorizedException`/`UserNotFoundException` → retorna `"invalid"` |
| `test_retorna_pending_quando_conta_esta_desabilitada_aguardando_aprovacao` | `NotAuthorizedException` com mensagem `"User is disabled."` → retorna status `"pending"` (distinto de senha incorreta, que usa o mesmo `Code` mas mensagem diferente) |
| `test_propaga_outros_codigos_de_erro` | Código de erro fora da lista tratada (ex: `TooManyRequestsException`) propaga `ClientError` para o chamador |
| `test_grava_timestamp_iso_utc_no_atributo_custom_last_login` | `record_login()` chama `AdminUpdateUserAttributes` gravando `custom:last_login` com um valor ISO 8601 parseável (não compara string exata — o timestamp é gerado no momento da chamada) |
| `test_grava_timestamp_iso_utc_no_atributo_custom_password_updated_at` | `record_password_update()` chama `AdminUpdateUserAttributes` gravando `custom:password_updated_at` com um valor ISO 8601 parseável, mesmo padrão de `record_login()` |
| `test_busca_por_email_e_extrai_atributos` (`TestGetUserProfile`) | `get_user_profile()` chama `ListUsers` filtrado por e-mail e retorna nome/e-mail via `_parse_user()` — usado por `profile.py` para pré-preencher a tela "Meu Perfil" |
| `test_grava_nome_no_atributo_name` (`TestUpdateUserName`) | `update_user_name()` chama `AdminUpdateUserAttributes` gravando o atributo `name` |
| `test_retorna_ok_e_define_senha_nova_quando_senha_atual_correta` (`TestChangePassword`) | `change_password()` reautentica via `authenticate()` e, com sucesso, chama `AdminSetUserPassword(Permanent=True)`, retornando `"ok"` |
| `test_retorna_invalid_sem_definir_senha_quando_senha_atual_incorreta` | Reautenticação falha → retorna `"invalid"` sem chamar `AdminSetUserPassword` |
| `test_define_senha_e_grava_nome_novo_sem_reautenticar` (`TestApplyResumedSignup`) | `apply_resumed_signup()` chama `AdminSetUserPassword(Permanent=True)` e `AdminUpdateUserAttributes` (atributo `name`) sem reautenticar via `AdminInitiateAuth` — usado por `forms.py::_render_signup_confirm` só depois de `confirm_sign_up()` validar o código, pra aplicar a senha/nome do cadastro retomado (a posse do código já é a prova de identidade, `change_password()` não serve aqui porque a conta já está `Disabled` nesse ponto) |
| `test_retorna_true_quando_usuario_pertence_ao_grupo_admins` / `test_retorna_false_quando_usuario_nao_pertence_ao_grupo_admins` | `is_admin()` checa `AdminListGroupsForUser` pelo `GroupName == "admins"` |
| `test_retorna_user_status_quando_lista_de_usuarios_nao_esta_vazia` / `test_retorna_none_quando_lista_de_usuarios_esta_vazia` | `get_user_status()` chama `ListUsers` com `Filter='email = "..."'` e retorna o `UserStatus` do primeiro usuário encontrado, ou `None` se a lista veio vazia — usado na tela "Esqueci a senha" pra avisar quando o e-mail não tem cadastro (`None`) ou ainda está pendente de aprovação (`"UNCONFIRMED"`) |
| `test_retorna_none_sem_chamar_a_api_quando_email_contem_aspas` | E-mail com `"` quebraria a sintaxe do `Filter` (sem escaping documentado) — `get_user_status()` retorna `None` sem chamar `ListUsers` |
| `test_busca_por_email_e_extrai_o_nome` (`TestGetUnconfirmedSignupName`) | `get_unconfirmed_signup_name()` chama `ListUsers` filtrado por e-mail e retorna o `name` do primeiro usuário — usado para pré-preencher o campo Nome na tela de confirmação de um cadastro retomado (`_start_signup_resume`, `forms.py`) |
| `test_levanta_index_error_quando_email_nao_existe` | Lista de usuários vazia → `IndexError` (contrato documentado: só deve ser chamada depois de `get_user_status()` confirmar `UNCONFIRMED`) |
| `test_chama_forgot_password_com_email` | `request_password_reset()` chama `ForgotPassword` com `ClientId`/`Username` |
| `test_chama_confirm_forgot_password_com_codigo_e_nova_senha` | `confirm_password_reset()` chama `ConfirmForgotPassword` com `ConfirmationCode`/`Password` |
| `test_filtra_por_status_disabled_e_extrai_atributos` | `list_pending_users()` chama `ListUsers` com `Filter='status = "Disabled"'` e extrai `email`/`name`/`enabled`/`created_at`/`updated_at`/`last_login` (`created_at` vem de `UserCreateDate`, campo nativo do item; `updated_at`/`last_login` vêm dos atributos custom `custom:password_updated_at`/`custom:last_login` em `Attributes`, lista de `{Name, Value}`, não dict) — os dois vêm `""` quando o atributo custom correspondente não existe |
| `test_extrai_last_login_quando_atributo_custom_existe` | Com `custom:last_login` presente em `Attributes`, `_parse_user()` extrai o valor de volta sem alteração |
| `test_extrai_updated_at_quando_atributo_custom_existe` | Mesmo teste, para `custom:password_updated_at` — gravado só por `record_password_update()` no fluxo de troca de senha, não por `UserLastModifiedDate` (nativo, mas descartado de propósito: reflete qualquer alteração na conta, inclusive cada login, o que tornaria a coluna redundante com "Último acesso") |
| `test_descarta_usuarios_que_ainda_nao_confirmaram_o_email` | `list_pending_users()` filtra em Python só `UserStatus == "CONFIRMED"` — quem ainda está `UNCONFIRMED` (não confirmou o e-mail) não aparece no painel admin |
| `test_filtra_por_status_enabled` | `list_active_users()` chama `ListUsers` com `Filter='status = "Enabled"'` |
| `test_descarta_usuarios_ainda_nao_confirmados_por_defesa` | `list_active_users()` também filtra em Python por `UserStatus == "CONFIRMED"`, defesa contra um caso que não deveria ocorrer no fluxo normal |
| `test_filtra_por_status_enabled` (`TestListUnconfirmedUsers`) | `list_unconfirmed_users()` chama `ListUsers` com o mesmo `Filter='status = "Enabled"'` de `list_active_users()` — reaproveita o filtro já testado em vez de introduzir uma sintaxe nova (ex.: `cognito:user_status`) |
| `test_mantem_apenas_usuarios_ainda_nao_confirmados` | `list_unconfirmed_users()` filtra em Python só `UserStatus == "UNCONFIRMED"` — espelho invertido de `list_active_users()`, para cadastros abandonados nesse estado (antes invisíveis nas duas listas) aparecerem no painel admin |
| `test_habilita_a_conta` (`TestApproveSignup`) | `approve_signup()` chama só `AdminEnableUser` — confirmação e verificação do e-mail já aconteceram via `confirm_sign_up()` do próprio usuário |
| `test_exclui_a_conta` (`TestRejectSignup`) | `reject_signup()` chama `AdminDeleteUser` |
| `test_exclui_a_conta` (`TestRevokeAccess`) | `revoke_access()` chama `AdminDeleteUser` — mesma decisão de sem histórico usada em `reject_signup()` |
| `test_adiciona_usuario_ao_grupo_admins` | `add_to_admins_group()` chama `AdminAddUserToGroup(GroupName="admins")` |
| `test_publica_no_topico_sns_com_email_e_nome` | `notify_new_signup()` chama `sns.publish` com `TopicArn`/`Subject`/`Message` (nome e e-mail interpolados, com o link do FilmBot no corpo) |

## Como executar

```bash
# Apenas os testes do lightsail
pytest test/lightsail_ia/ -v

# Com cobertura
pytest test/lightsail_ia/ --cov=app/lightsail_ia --cov-report=term-missing
```

## Cobertura mínima

**95%** — definido via `--cov-fail-under=95` no workflow de CI (`.github/workflows/01_test.yml`). `app.py`, `forms.py`, `admin.py`, `profile.py`, `recommendation.py` e `cards.py` estão formalmente excluídos dessa medição via `omit=` no `.coveragerc` (ver seção abaixo) — não contam nem a favor nem contra o gate. `infrastructure.py`/`components.py` **não** estão excluídos: embora também tenham código chamado pela UI, têm funções puras, com saída antecipada, ou chamadas diretas a boto3 (Cognito/SNS) trivialmente testáveis via mock, sem depender de um script Streamlit rodando (ver `test_infrastructure.py`/`test_components.py` acima).

## Observação sobre testes de interface

A interface Streamlit (`app.py`, `forms.py`, `admin.py`, `profile.py`, `recommendation.py`, `cards.py`) não é coberta por testes automatizados nesta suite — e por isso está listada em `omit=` no `.coveragerc`, no mesmo mecanismo usado para excluir `test/*`/`infra/*` do gate. Sem essa exclusão, esses arquivos ficariam em 0% de cobertura (rodam código a nível de import/execução de script, sem framework tipo `st.testing.v1.AppTest` no projeto) e derrubariam o gate de 95% sozinhos. Para validar o app visualmente, execute localmente:

```bash
cd app/lightsail_ia
streamlit run app.py
```

A variável `CLOUDWATCH_LOG_GROUP` não é definida no conftest — isso é intencional: sem ela, o handler watchtower não é ativado e os testes rodam sem dependência do CloudWatch.

