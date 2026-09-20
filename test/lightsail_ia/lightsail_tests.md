# Testes — lightsail_ia

## O que é testado

Testa as funções do agente de recomendação (`app/lightsail_ia/agent.py`), as funções de formatação (`app/lightsail_ia/formatting.py`), os componentes de renderização HTML (`app/lightsail_ia/components.py`) e o bootstrap de processo/rate limiting (`app/lightsail_ia/infrastructure.py`). O `test_agent.py` cobre `recommend()`, `search_titles_spec()`, validação SQL, extração de termos de gênero/provedor para destaque nas badges, cache e logging de tokens. O `test_formatting.py` cobre as funções puras de formatação (`format_record`, `_format_type`, `_format_genres`, `_format_title_duration`, `_format_release_date`, `_format_theater_end_date`, `_format_rating`). O `test_components.py` cobre a renderização de cards e grids (`render_card`, `render_grid`), a priorização de badges por termo destacado (`_prioritize`), a caixa de mensagem de feedback padronizada (`render_feedback`), os rodapés (`render_footer`/`render_form_footer`, incluindo o link de contato por e-mail via `_render_contact_line()`), o helper de ícone Lucide (`icon()`/`ICON_PATHS`) e a injeção dos scripts `load_audio_timer_script`/`load_countdown_script`/`load_form_button_toggle_script`, incluindo escape XSS e verificação de campos exibidos/ignorados. O `test_infrastructure.py` cobre os ramos de saída antecipada de `load_filmbot_password`/`setup_cloudwatch_logging` (sem tocar AWS de verdade), as funções puras de rate limiting (`get_client_ip`, `events_in_window`, `seconds_until_available`) e as chamadas Cognito/SNS da autenticação e do perfil (`sign_up`, `confirm_sign_up`, `resend_confirmation_code`, `authenticate`, `record_login`, `record_password_update`, `is_admin`, `get_user_status`, `get_user_profile`, `update_user_name`, `change_password`, `request_password_reset`, `confirm_password_reset`, `list_pending_users`, `list_active_users`, `list_unconfirmed_users`, `approve_signup`, `reject_signup`, `revoke_access`, `add_to_admins_group`, `notify_new_signup`) — todas mockando `boto3.client` diretamente, mesmo padrão já usado pelo resto do arquivo, sem `moto`. O `test_app.py` cobre o entrypoint Streamlit (`app.py`) via `streamlit.testing.v1.AppTest` — primeiro uso desse framework no projeto (ver nota abaixo). Como `app.py` roda tudo a nível de módulo na importação (sem nenhuma função isolada pra chamar), é o único módulo da suíte que precisa dele. O `test_recommendation.py` cobre `render_recommendation()` — a tela de captura de preferência (texto/áudio) e a busca assíncrona de recomendação, a função Streamlit mais complexa do projeto (354 linhas, sem nenhuma sub-função privada extraída, ~15 chaves de `session_state`). Substitui `concurrent.futures.Future` por um fake controlável (`_FakeFuture`) para não depender de threads reais, e intercepta `st.rerun`/`time.sleep` (ver nota abaixo) — praticamente todo ramo desta função termina em `st.rerun()`. O `test_forms.py` cobre as 5 telas de autenticação de `forms.py` (login, cadastro, retomada de cadastro, confirmação de e-mail, esqueci a senha) — validações puras, dispatch de view (`render_forms`), rate limiting por IP em 5 dicts `@st.cache_resource` distintos, e os blocos `@st.fragment(run_every=1)` aninhados (mensagem de reenvio de código com contagem regressiva), substituindo `st.fragment` por um decorator identidade (ver nota abaixo). O `test_admin.py` cobre o painel administrativo (`admin.py`): as funções puras de montagem/rótulo da tabela (`_status_label`, `_revoke_kind`, `_revoke_visible`, `_build_rows`, `_build_table_data`, `_build_table_html`/`_build_table_row_html`, `_format_datetime`), o dispatch de cliques da tabela via componente customizado Shadow DOM (`_render_users_table`, com `st.components.v2.component` substituído por um fake que simula o objeto de retorno) e o modal de confirmação de ação (`_render_confirm_dialog`, chamado via `.__wrapped__` para pular a abertura real do `@st.dialog`, que precisa de um script run ativo). O `test_profile.py` cobre a edição de nome/senha do próprio usuário (`profile.py`): `_validate_new_password` (pura), `get_own_profile` (com fallback em `ClientError`), a barra de navegação reaproveitável (`render_nav_item`/`render_nav_bar`), a aba "Perfil" (`render_profile_tab`) e a aba "Senha" com rate limiting por IP (`render_password_tab`), e o dispatch entre as duas (`render_profile_panel`). O `test_cards.py` cobre `render_cards()` — a exibição da grid de resultados a partir de `st.session_state["titles"]` (singular/plural do texto de contagem, ausência/presença de títulos, um card por título). Os testes usam estilo **pytest** (classes simples, `assert` nativo, `with patch(...)` como context manager). A interface Streamlit (`app.py`, `forms.py`, `admin.py`, `profile.py`, `recommendation.py`) ainda não é testada diretamente — é validada via execução manual (ver "Observação sobre testes de interface" abaixo; `cards.py` já saiu dessa lista). Todas as chamadas externas (LLM e Athena) são substituídas por **mocks** via `unittest.mock` — objetos falsos que simulam respostas do LLM e do banco de dados sem fazer chamadas reais, evitando custos de API e tornando os testes determinísticos.

## Estrutura

```
test/lightsail_ia/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_admin.py              # Testes do painel administrativo
├── test_agent.py             # Testes do agente (LLM, Athena, cache, validação)
├── test_app.py                # Testes do entrypoint Streamlit via AppTest
├── test_cards.py              # Testes da exibição da grid de resultados
├── test_components.py       # Testes de renderização HTML (cards e grids)
├── test_formatting.py        # Testes das funções puras de formatação
├── test_forms.py              # Testes das telas de autenticação
├── test_infrastructure.py    # Testes do bootstrap de processo e rate limiting
├── test_profile.py           # Testes de edição de nome/senha do próprio usuário
└── test_recommendation.py    # Testes da captura de preferência e busca assíncrona
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

As variáveis acima usam `setdefault` (preservam um valor real já exportado). Já `FILMBOT_SECRET_ARN` e `CLOUDWATCH_LOG_GROUP` são **forçadas para vazio** (`os.environ[...] = ""`): `agent.py` chama `load_dotenv()`, que não sobrescreve variável já definida (nem vazia), e um `app/lightsail_ia/.env` de desenvolvimento com elas preenchidas fazia o `AppTest` (`test_app.py`) executar `setup_cloudwatch_logging()`/`load_filmbot_password()` de verdade — handler real do CloudWatch, chamada real ao Secrets Manager e root logger derrubado para `ERROR` pelo resto da sessão, o que quebrava os testes de log (`caplog`) de `test/scripts` e `test/shared_src` só na máquina do desenvolvedor (o CI não tem `.env`).

As credenciais AWS (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`) também são forçadas para `"testing"` e `AWS_PROFILE` é removido: uma chamada `boto3` esquecida sem mock falha por credencial inválida em vez de usar as chaves reais do `.env`. Além disso, `test/conftest.py` bloqueia qualquer conexão de rede para fora do loopback durante toda a suíte (`test/test_bloqueio_de_rede.py` cobre essa trava).

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
| `test_levanta_erro_quando_athena_falha_ou_e_cancelada` (parametrizado: `FAILED`/`CANCELLED`) | Estado terminal de erro do Athena levanta `RuntimeError` com o `StateChangeReason` e não lê resultados |
| `test_aguarda_e_repete_o_polling_enquanto_a_query_esta_em_execucao` | `QUEUED`/`RUNNING` repetem o polling (com `time.sleep` mockado) até `SUCCEEDED` |
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
| `test_pool_nao_ultrapassa_maximo_absoluto` | Pool nunca ultrapassa `_CANDIDATE_POOL_MAX` (30), mesmo quando `limit * _CANDIDATE_POOL_MULTIPLIER` seria maior |
| `test_amostra_e_limitada_ao_limit_solicitado_quando_pool_maior` | Pool com mais linhas que `limit` → resultado final tem exatamente `limit` títulos |
| `test_retorna_todos_quando_pool_nao_excede_limit` | Pool com menos linhas que `limit` → retorna todas, sem erro |
| `test_amostra_preserva_ordem_de_popularidade_do_subconjunto` | Mesmo com as menores chaves de `secrets.randbits` caindo em índices fora de ordem, o resultado final preserva a ordem original (popularidade DESC) entre os títulos escolhidos |
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
| `test_passos_1_e_3_repassam_fallback_de_modelo_do_openrouter` | As duas chamadas recebem `extra_body={"models": _LLM_FALLBACK_MODELS}` — fallback nativo do OpenRouter, acionado se o modelo principal (`LLM_MODEL`) falhar |
| `test_retorna_lista_vazia_se_llm_nao_chama_tool` | Retorna `[]` sem chamar Athena quando o LLM não retorna `tool_calls` (ex: modelo não escolhe usar a tool) |
| `test_retorna_lista_vazia_se_argumentos_da_tool_call_sao_json_invalido` | Retorna `[]` sem chamar Athena quando `tool_call.function.arguments` é JSON inválido (ex: resposta cortada do LLM), sem levantar exceção — mesma degradação graciosa já usada no motivo da etapa 3 |
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

### `TestFiltroDeRelevanciaNoPasso3` — `relevant: false` do Passo 3 descarta títulos

| Teste | O que verifica |
|---|---|
| `test_descarta_titulo_marcado_como_irrelevante_e_mantem_os_demais` | Título com `relevant: false` sai do resultado; os demais ficam com o `reason` correto (alinhamento por índice preservado) |
| `test_loga_titulos_descartados_como_info` | Descarte parcial loga `logger.info` com `discarded_count`, `total_titles`, `discarded_titles` e `preference` |
| `test_retorna_lista_vazia_e_loga_aviso_quando_todos_sao_irrelevantes` | Todos descartados → `[]` + `logger.warning` (sinal de `WHERE` ruim) |
| `test_mantem_titulo_quando_relevant_nao_e_false_literal` | `relevant` `None`/`"false"`/`0`/`"no"` não descarta — só `False` literal |
| `test_mantem_titulo_quando_relevant_esta_ausente` | Item sem a chave `relevant` mantém o título (tolerância a variação de resposta do LLM) |
| `test_ignora_relevant_false_de_item_com_id_invalido_ou_ausente` | `relevant: false` em item com `id` não conversível ou ausente não descarta nada |
| `test_id_como_string_tambem_descarta` | `id` como string (`"1"`) também identifica o título a descartar |
| `test_prompt_do_passo_3_pede_o_campo_relevant` | `_REASON_SYSTEM_PROMPT` menciona `relevant` e a regra "na dúvida, marque true" |

### `TestLogsDeDiagnosticoDaBusca` — Logs que ligam o `WHERE` ao pool do Athena

| Teste | O que verifica |
|---|---|
| `test_loga_where_clause_e_limit_do_passo_1` | `recommend()` loga "Filtros do Passo 1" com `preference`, `where_clause` e `limit` vindos do LLM |
| `test_loga_limit_padrao_quando_llm_nao_informa` | Sem `limit` nos argumentos, o log usa `_DEFAULT_RECOMMENDATION_COUNT` |
| `test_loga_tamanho_do_pool_devolvido_pelo_athena` | `search_titles_spec` loga `pool_size`, `pool_returned` (antes do sorteio) e `limit` |

### `TestLoadApiKeys` — Chaves de LLM/transcrição (Secrets Manager × ambiente)

| Teste | O que verifica |
|---|---|
| `test_llm_key_vem_do_secrets_manager_quando_arn_configurado` / `test_llm_key_vem_do_ambiente_sem_arn` | `_load_llm_api_key` lê `llm_api_key` do secret com `FILMBOT_SECRET_ARN`, ou `LLM_API_KEY` do ambiente sem ele (sem chamar `boto3`) |
| `test_transcription_key_vem_do_secrets_manager_quando_arn_configurado` / `test_transcription_key_vem_do_ambiente_sem_arn` | Idem para `_load_transcription_api_key` / `TRANSCRIPTION_API_KEY` |
| `test_transcription_key_ausente_no_secret_retorna_none_sem_derrubar_o_app` | Campo opcional ausente no secret → `None` (usa `.get()`, não indexação), sem `KeyError` |

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

## Casos de teste — `test_cards.py`

### `TestRenderCards` — Exibição da grid de resultados

O padrão de mock aqui difere do resto da suíte: como `render_cards()` é uma função de UI que só lê `st.session_state` e chama `st.markdown`, os testes capturam todas as chamadas de `cards.st.markdown` numa lista (via `monkeypatch.setattr`), em vez de mockar um único retorno — a 1ª chamada é sempre a injeção de CSS (`load_cards_css()`), a 2ª (quando há títulos) é o texto de contagem, a 3ª é a grid.

| Teste | O que verifica |
|---|---|
| `test_sem_titulos_nao_renderiza_heading_nem_grid` | `session_state` sem a chave `titles` → só a injeção de CSS chama `st.markdown` |
| `test_lista_vazia_de_titulos_nao_renderiza_heading_nem_grid` | `titles=[]` → mesmo comportamento acima |
| `test_um_titulo_usa_singular_opcao` | Um título → texto "Encontramos 1 opção para você!" (singular) |
| `test_varios_titulos_usa_plural_opcoes` | Mais de um título → texto no plural ("opções") |
| `test_renderiza_um_card_por_titulo_na_grid` | A grid final contém exatamente um `<article class="card">` por título, com o nome de cada um |
| `test_ausencia_de_titles_em_session_state_equivale_a_lista_vazia` | Confirma que `.get("titles", [])` trata chave ausente igual a lista vazia |

## Casos de teste — `test_components.py`

### `TestLoadCssPorTela` — Loaders de CSS por tela

| Teste | O que verifica |
|---|---|
| `test_cada_loader_injeta_o_css_da_sua_tela` | `load_recommendation_css`/`load_cards_css`/`load_admin_css`/`load_profile_css` delegam a `_inject_css` com o arquivo correto |

### `TestLoadScriptsEstaticos` — Loaders de scripts JS estáticos

| Teste | O que verifica |
|---|---|
| `test_contador_substitui_placeholders_com_rate_limit_desligado` / `test_contador_marca_rate_limited_quando_ativo` | `load_preference_counter_script` substitui `__MAX_CHARS__` e `__RATE_LIMITED__` (`false` por padrão, `true` quando rate limited) |
| `test_audio_cancel_injeta_script_com_altura_zero` / `test_textarea_autogrow_injeta_script_com_altura_zero` | Scripts sem placeholder são injetados via `components.html` com `height=0` |

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
| `test_mes_fora_do_intervalo_retorna_none` | `"1980-13-01"` → `None` |
| `test_ano_nao_numerico_retorna_none` | `"abcd-05-01"` → `None` |

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
| `test_string_nao_numerica_retorna_none` | `"sem nota"` → `None` |
| `test_tipo_invalido_retorna_none` | Tipo não conversível (ex.: lista) → `None` |

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

### `TestLoadFilmbotPasswordGravaSecretsToml` — Ramo que grava `secrets.toml`

| Teste | O que verifica |
|---|---|
| `test_grava_secrets_toml_com_a_senha_do_secret` | Com `boto3` mockado e `infrastructure.__file__` apontando para `tmp_path` (nunca o `.streamlit/` real), grava `[auth]\npassword = "..."` |
| `test_secrets_toml_fica_com_permissao_restrita_ao_dono` | Em POSIX o arquivo fica `0o600`; no Windows só confirma que foi criado (`chmod` não expressa 0o600 lá) |

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

## Casos de teste — `test_app.py` (primeiro uso de `streamlit.testing.v1.AppTest` no projeto)

`app.py` não expõe nenhuma função chamável isoladamente — todo o corpo roda a nível de módulo assim que é importado. `AppTest.from_file(caminho_absoluto_de_app.py)` resolve isso executando o script de verdade a cada `.run()`/`.click().run()` (widgets reais respondem, `st.session_state` é um proxy real que persiste entre reruns simulados, exatamente como uma sessão de navegador). Diferente do resto da suíte (que sempre mocka `st.*` diretamente), aqui o padrão é mockar as funções **delegadas** que `app.py` importa de outros módulos (`admin.render_admin_panel`, `profile.render_profile_panel`, `recommendation.render_recommendation`, `cards.render_cards`, `components.render_footer`) — já que os `from src.X import Y` de `app.py` são resolvidos de novo em cada execução, basta o monkeypatch estar aplicado no módulo de origem antes de chamar `.run()`.

**Achado importante, validado manualmente antes de escrever os testes**: sem mockar `render_admin_panel`/`render_profile_panel`, o app tenta chamar a API real do Cognito (`list_pending_users`/`get_own_profile`) assim que a tela renderiza — e numa máquina com credenciais AWS ambiente configuradas, isso dispara uma chamada de rede real (confirmado experimentalmente: um `AccessDeniedException` real de uma identidade IAM real apareceu no meio da investigação). Por isso os 5 `render_*` delegados são **sempre** mockados neste arquivo antes de qualquer `.run()`.

**Limitação encontrada e contornada**: `infrastructure.get_client_ip`/`load_filmbot_password`/`setup_cloudwatch_logging` **não são mockados** de propósito — o mecanismo de alias `src.*` do `conftest.py` global (que permite várias suítes de teste compartilharem o mesmo processo pytest, ver seção do `conftest.py` acima) carrega `infrastructure` por um caminho de import diferente do resto, porque `recommendation.py` (o módulo-âncora da suíte) importa `infrastructure` internamente **antes** do alias canônico `src → app.lightsail_ia.src` ser estabelecido — um monkeypatch aplicado no objeto `infrastructure` do lado do teste não é o mesmo objeto que `app.py` resolve durante a execução do `AppTest`. Confirmado isolando o caso: os 5 `render_*` acima respeitam o monkeypatch normalmente (cada um deles é importado por um caminho que já usa o alias canônico), só `infrastructure` diverge. Como as 3 funções já são seguras de rodar de verdade em teste (sem `FILMBOT_SECRET_ARN`/`CLOUDWATCH_LOG_GROUP` no ambiente, as duas de bootstrap retornam sem tocar AWS; `get_client_ip()` sem header `X-Forwarded-For` real — nunca presente no `AppTest` — sempre retorna `"local"`), os testes abaixo comparam contra `"local"` em vez de mockar um IP arbitrário. Se um dia isso precisar de um IP customizado de verdade, a correção pertence ao `conftest.py` global (fazer `recommendation.py` importar `infrastructure` só depois do alias, ou pré-popular o alias antes do import do módulo-âncora), não a este arquivo de teste.

### `TestGateDeAutenticacao`

| Teste | O que verifica |
|---|---|
| `test_nao_autenticado_mostra_login_e_nao_renderiza_header` | Sem `authenticated=True`, `render_forms` real (não mockado) renderiza a tela de login de verdade e chama `st.stop()` — nenhum dos 5 `render_*` delegados é chamado, confirmando que o gate de autenticação corta a execução antes do cabeçalho/dispatch |

### `TestDispatchPrincipal`

| Teste | O que verifica |
|---|---|
| `test_nao_admin_sem_view_mostra_recomendacao_e_cards` | Autenticado, não-admin, sem `current_view` → tela principal (`render_recommendation`+`render_cards`), com `render_footer` chamado ao final |
| `test_nao_admin_view_profile_mostra_perfil` | `current_view="profile"` → só `render_profile_panel` |
| `test_admin_sem_view_mostra_recomendacao_e_cards` | Admin também vê a tela principal por padrão, igual não-admin |
| `test_admin_view_admin_mostra_painel` | Admin com `current_view="admin"` → só `render_admin_panel` |
| `test_view_admin_sem_ser_admin_e_ignorado` | `current_view="admin"` sem `is_admin=True` (sobra de sessão anterior, ex.: um admin perdeu o cargo) → painel admin NUNCA abre, cai na tela principal — confirma que o dispatch exige as duas condições (`is_admin and current_view == "admin"`) juntas |

### `TestBarraDeNavegacao`

| Teste | O que verifica |
|---|---|
| `test_admin_ve_botao_painel_admin_nao_meu_perfil` / `test_nao_admin_ve_botao_meu_perfil_nao_painel_admin` | Mutuamente exclusivos — admin nunca vê "Meu Perfil", não-admin nunca vê "Painel Admin" |
| `test_clique_no_toggle_admin_alterna_para_painel_e_de_volta` / `test_clique_no_toggle_perfil_alterna_para_perfil_e_de_volta` | Clique alterna `current_view` (`"app"`↔`"admin"`/`"profile"`) e o rótulo do botão (`"Painel Admin"`/`"Meu Perfil"` ↔ `"← App"`) |
| `test_clique_em_sair_limpa_toda_a_sessao` | "Sair" limpa `session_state` por completo (`.clear()`, não só `authenticated`) — confirma que resquícios de uma sessão anterior (`titles`, `user_name`) não vazam pro próximo login |

## Casos de teste — `test_recommendation.py`

Duas técnicas de mock específicas deste módulo, no helper comum `_stub(monkeypatch, initial_state, rerun_raises=True)` (por padrão `True`, diferente de `forms.py`, porque aqui praticamente todo ramo termina em `st.rerun()` — o helper já assume isso e cada teste que não deve disparar rerun escolhe `rerun_raises=False` ou apenas confere `rerun.assert_not_called()`):
- `concurrent.futures.Future` real (retornado por `_executor.submit`) é substituído por `_FakeFuture` (classe local com `.done()`/`.result()` controláveis), evitando depender de threads de verdade ou de tempo real de execução do LLM/Whisper.
- `st.rerun()` sempre levanta uma exceção sentinela (`_Rerun`, capturada via `pytest.raises`) por padrão — reproduz o corte de execução real do Streamlit (sem isso, em modo bare o código depois do rerun continuaria executando e misturaria estados de branches diferentes numa única chamada, já que esta função não tem nenhuma sub-função privada para isolar os ramos). `time.sleep` também é mockado, para os dois pontos de polling (`transcribing`/`searching`) não pausarem os testes de verdade.

### `TestGreeting` / `TestEstadoOcioso`

Saudação com/sem primeiro nome; e o estado ocioso completo (sem áudio, sem busca) não deve chamar `st.rerun()` nenhuma vez.

### `TestCapturaDeAudio` — Novo áudio gravado

| Teste | O que verifica |
|---|---|
| `test_audio_novo_dentro_do_limite_marca_aguardando_confirmacao` | Áudio dentro do limite de duração → grava hash/bytes pendentes, `audio_awaiting_confirmation=True` |
| `test_audio_muito_longo_marca_flag_sem_pedir_confirmacao` | Acima do limite (+ tolerância) → `transcription_too_long=True`, pula a confirmação, incrementa `audio_widget_seq` |
| `test_mesmo_audio_de_antes_nao_reprocessa` | Hash igual ao último processado → não reprocessa, sem `st.rerun()` |

### `TestConfirmacaoDeAudio` — Usar/cancelar gravação

| Teste | O que verifica |
|---|---|
| `test_rate_limit_atingido_cancela_confirmacao_automaticamente` | Limite de transcrições/hora atingido → cancela a confirmação sozinho, marca `transcription_rate_limited` |
| `test_usar_gravacao_submete_transcricao_no_executor` | Clique em "Usar gravação" → `_executor.submit(transcribe_preference, bytes)`, `transcribing=True` |
| `test_cancelar_gravacao_descarta_bytes_pendentes` | Clique em "Cancelar" → descarta os bytes, sem submeter nada |
| `test_sem_clique_mantem_estado_de_confirmacao_sem_rerun` | Nenhum clique → estado inalterado, sem `st.rerun()` |

### `TestTranscricaoEmAndamento` — Polling do resultado da transcrição

Cobre: ainda não concluída (mostra status, `time.sleep`, rerun); concluída com texto (grava `preference_text`); concluída sem texto (`transcription_empty`); texto acima do limite de caracteres (trunca + `transcription_truncated`); `AudioMuitoLongoError` durante a transcrição (`transcription_too_long`); e exceção genérica (`transcription_error`, logada).

### `TestMensagensDeTranscricao`

Cada uma das 5 flags de aviso (`transcription_rate_limited`, `transcription_too_long`, `transcription_error`, `transcription_empty`, `transcription_truncated`) renderiza a mensagem certa via `render_feedback`, isoladamente.

### `TestBotaoRecomendar` — Disparo da busca

Cobre o aviso de limite de consultas/hora com countdown, a classe CSS de destaque quando o contador está baixo (≤3), o clique com preferência preenchida (submete `recommend` no executor e inicia `searching`), e o clique sem preferência (guard `and preference` impede o submit).

### `TestBuscaEmAndamento` — Polling do resultado da busca

Cobre: ainda buscando (spinner + `time.sleep` + rerun); "Cancelar" reseta todo o estado de busca; conclusão com sucesso (grava `titles`); conclusão com erro (`search_error=True`, `titles=[]`).

### `TestFeedbackDeResultado`

Erro de busca e "sem resultados" renderizam a mensagem certa; resultado com títulos não renderiza nenhum feedback de erro/vazio.

## Casos de teste — `test_forms.py`

Duas técnicas de mock específicas deste módulo, usadas por praticamente toda classe de teste via um helper comum `_stub_common(monkeypatch, initial_state, rerun_raises=False)`:
- **`st.fragment(run_every=1)` não executa a função decorada em modo bare** (nenhuma exceção — o agendamento de `run_every` depende do `ScriptRunContext` real, então o Streamlit simplesmente não chama o corpo). `_stub_common` substitui `forms.st.fragment` por um decorator identidade (`lambda *a, **k: (lambda f: f)`), necessário para que as 3 seções de reenvio/envio (`_resend_section` em `_render_signup_confirm`/`_render_forgot_password_confirm`, `_send_section` em `_render_forgot_password_request`) de fato executem quando a função-mãe é chamada.
- **`st.rerun()` real não interrompe a execução em modo bare** (é um no-op) — mas em produção ele aborta o script imediatamente, então código escrito depois de um `st.rerun()` nunca roda de verdade. Onde isso importa (ex.: confirmar que a mensagem de erro NÃO aparece depois que o lockout é atingido no meio de uma tentativa), o teste passa `rerun_raises=True` para `_stub_common`, que faz o mock de `st.rerun` levantar uma exceção sentinela (`_Rerun`) capturada via `pytest.raises(_Rerun)` — reproduzindo fielmente o corte de execução real.

Fixture `autouse` (`_limpar_rate_limit_histories`) limpa os 5 dicts `@st.cache_resource` de rate limiting do módulo (`_login_attempt_history`, `_reset_attempt_history`, `_code_attempt_history`, `_signup_code_send_history`, `_signup_code_attempt_history`) antes de cada teste. `st.text_input`/`st.button` são substituídos por lambdas que retornam valores fixos por `key` (`_patch_text_input`/`_patch_button`), mesmo padrão de `test_profile.py`/`test_admin.py`.

### Funções puras (`TestValidateSignup`, `TestSignupErrorMessage`, `TestValidateSignupResumeDetails`, `TestSignupCodeErrorMessage`, `TestValidateReset`, `TestResetErrorMessage`, `TestSwitchView`, `TestBrandHeader`)

Tabelas de validação client-side (campos em branco, e-mail inválido, senhas divergentes, delega pra `validate_password`) e de tradução de código de erro do Cognito (`CodeMismatchException`, `ExpiredCodeException`, `UsernameExistsException`, `InvalidPasswordException`, `LimitExceededException`/`TooManyFailedAttemptsException`, `AliasExistsException`, `UserNotFoundException`, código desconhecido) para cada uma das 3 telas com código (cadastro, confirmação de cadastro, redefinição de senha). `TestSwitchView` confirma que troca de view grava `session_state["auth_view"]` e chama `st.rerun()`; `TestBrandHeader` confirma a renderização condicional do título de página.

### `TestStartSignupResume` — Retomada de cadastro abandonado (lógica de negócio sem widgets Streamlit)

| Teste | O que verifica |
|---|---|
| `test_email_nao_pendente_retorna_not_pending_sem_reenviar` | E-mail não `UNCONFIRMED` no Cognito → `"not_pending"`, sem reenviar código |
| `test_pendente_reenvia_codigo_e_retorna_ok` | E-mail pendente → reenvia código, grava `signup_email_confirmed`/`signup_name_confirmed`/`signup_resumed=True`, retorna `"ok"` |
| `test_dentro_do_cooldown_nao_reenvia_mas_ainda_retorna_ok` | Reenvio recente (dentro do cooldown de 60s) → não reenvia de novo, mas ainda retorna `"ok"` (já tem código válido) |
| `test_falha_ao_reenviar_retorna_resend_failed` | Erro real do Cognito ao reenviar → `"resend_failed"` |
| `test_erro_ao_buscar_nome_usa_string_vazia_mas_ainda_retorna_ok` | Falha ao buscar nome pré-existente (`ClientError`/`IndexError`) → nome vira `""`, mas o fluxo continua (`"ok"`) |

### `TestRenderForms` — Dispatch da view ativa

Confirma que `authenticated=True` retorna sem renderizar nada, que cada valor de `auth_view` despacha para a função `_render_*` certa (`signup`, `signup_resume`, `signup_confirm`, `signup_success`, `forgot_password`, `password_reset_success`, e o padrão `login`), e que `st.stop()` é sempre chamado ao final (exceto no caminho já autenticado).

### `TestRenderLoginForm` — Tela de login

| Teste | O que verifica |
|---|---|
| `test_bloqueado_mostra_aviso_sem_chamar_authenticate` | 3 tentativas na janela de 60s → aviso com countdown, sem chamar `authenticate` |
| `test_login_bem_sucedido_grava_sessao_e_chama_rerun` | Sucesso → grava `authenticated`/`user_email`/`is_admin`/`user_name`, chama `record_login`, `st.rerun()` |
| `test_login_bem_sucedido_com_falha_ao_buscar_nome_usa_string_vazia` / `test_login_bem_sucedido_com_falha_ao_gravar_last_login_nao_propaga` | Falhas não-críticas (nome/last_login) não travam o login |
| `test_login_pending_mostra_aviso_sem_rerun` | Cadastro ainda não aprovado → aviso, sem `st.rerun()` |
| `test_credenciais_invalidas_registra_falha_e_mostra_erro` | Credencial errada (1ª/2ª tentativa) → registra tentativa, mostra erro, sem rerun |
| `test_terceira_credencial_invalida_chama_rerun_sem_mostrar_erro` | 3ª tentativa errada → `st.rerun()` (mostra a tela de lockout no próximo render) SEM chegar a mostrar "E-mail ou senha incorretos." (usa `rerun_raises=True`/`pytest.raises` pra provar o corte de execução real) |
| `test_submit_sem_preencher_campos_mostra_erro` | Campos vazios → erro local, sem chamar `authenticate` |
| `test_link_esqueci_a_senha_troca_view` / `test_link_novo_cadastro_troca_view` | Links secundários chamam `_switch_view` com o destino certo |

### `TestRenderSignup` — Formulário de cadastro

| Teste | O que verifica |
|---|---|
| `test_cadastro_valido_chama_sign_up_e_agenda_cooldown_de_reenvio` | Cadastro válido → `sign_up`, grava e-mail/nome confirmados, inicia cooldown de reenvio, vai para `signup_confirm` |
| `test_validacao_local_falha_nao_chama_sign_up` | Validação local falha → não chama Cognito |
| `test_email_ja_existente_com_retomada_bem_sucedida_vai_para_confirmacao` / `test_email_ja_existente_sem_retomada_mostra_erro` | `UsernameExistsException` tenta retomar via `_start_signup_resume`; sucesso pula pra confirmação, falha mostra "já está cadastrado" |
| `test_erro_generico_do_cognito_mostra_mensagem_de_erro` | Outro erro do Cognito → mensagem genérica |
| `test_link_retomar_cadastro_troca_view` / `test_link_voltar_ao_login_troca_view` | Links secundários |

### `TestRenderSignupResumeRequest` — Link dedicado "Já iniciei um cadastro"

Cobre e-mail inválido (sem chamar `_start_signup_resume`), os 3 resultados possíveis (`ok`/`not_pending`/`resend_failed`) e o link de voltar ao login.

### `TestRenderSignupConfirm` — Confirmação de e-mail (a mais complexa: código + resend fragment + retomada)

| Teste | O que verifica |
|---|---|
| `test_retomada_na_etapa_details_delega_para_resume_details` | `signup_resumed=True` + `signup_resume_step="details"` → early return delegando pra `_render_signup_resume_details` |
| `test_bloqueado_mostra_aviso_sem_chamar_confirm_sign_up` / `test_terceiro_codigo_incorreto_chama_rerun_sem_mensagem_de_erro` | Lockout de código (3 tentativas) — inclusive o corte de execução real via `rerun_raises=True` |
| `test_codigo_em_branco_mostra_erro` / `test_codigo_incorreto_registra_tentativa_e_mostra_erro` | Validação de código |
| `test_confirmacao_bem_sucedida_nao_retomada_vai_para_tela_de_sucesso` / `test_confirmacao_bem_sucedida_retomada_avanca_para_etapa_details` | Sucesso bifurca por `resumed` |
| `test_falha_ao_notificar_admin_nao_propaga` | Falha ao notificar admin não trava a confirmação do próprio usuário |
| `test_resend_section_sem_bloqueio_nao_mostra_mensagem` / `..._com_reenvio_recente_mostra_sucesso` / `..._com_falha_recente_mostra_erro` / `..._sem_reenvio_nem_falha_recente_mostra_aviso_generico` | Os 4 estados de mensagem do fragment de reenvio (nenhum bloqueio, sucesso recente, falha recente, bloqueio genérico) |
| `test_clique_em_reenviar_codigo_com_sucesso` / `test_clique_em_reenviar_codigo_com_falha` | Clique em "Reenviar código" dentro do fragment |
| `test_link_voltar_ao_login_dentro_do_resend_limpa_sessao_e_troca_view` | Link "Voltar ao login" dentro do fragment também limpa o estado de cadastro |
| `test_sem_email_confirmado_mostra_subtitulo_generico` | Sem e-mail em sessão, mostra subtítulo genérico em vez do aviso "Enviamos um código para..." |

### `TestRenderSignupResumeDetails` — Nome/senha finais do cadastro retomado

Cobre aplicação bem-sucedida (`apply_resumed_signup`), falha não-propagante, validação local, o link "← Voltar" (volta pra etapa de código) e escape XSS do e-mail somente-leitura.

### `TestRenderForgotPassword` / `TestRenderSignupSuccess` — Dispatch simples

`TestRenderForgotPassword` cobre o dispatch por `reset_step` (`"request"`/`"confirm"`); `TestRenderSignupSuccess` cobre o único botão da tela de sucesso do cadastro.

### `TestRenderForgotPasswordRequest` — Passo 1 do "Esqueci a senha" (fragment `_send_section`)

| Teste | O que verifica |
|---|---|
| `test_bloqueado_mostra_aviso_generico` / `..._com_email_nao_registrado_mostra_mensagem_especifica` / `..._com_cadastro_pendente_mostra_mensagem_especifica` | As 3 mensagens possíveis durante o cooldown, conforme as flags `email_not_registered`/`email_pending_approval` |
| `test_email_invalido_mostra_erro` | Valida o e-mail lido de `session_state["reset_email"]` (não da variável local — o fragment roda isolado do resto do form) |
| `test_email_sem_cadastro_marca_flag_e_faz_rerun_de_fragmento` / `test_email_pendente_de_aprovacao_marca_flag_e_faz_rerun_de_fragmento` | `get_user_status` `None`/`"UNCONFIRMED"` → marca a flag certa, sem chamar `request_password_reset`, `st.rerun(scope="fragment")` |
| `test_email_confirmado_solicita_reset_e_avanca_para_confirmacao` | Status confirmado → `request_password_reset`, avança pra `reset_step="confirm"` |
| `test_falha_ao_solicitar_reset_nao_propaga` | Erro do Cognito nesse ponto não deve vazar detalhe pro usuário (anti-enumeration) |
| `test_link_voltar_ao_login_troca_view` | Link fora do fragment |

### `TestRenderForgotPasswordConfirm` — Passo 2 do "Esqueci a senha" (código + nova senha + fragment `_resend_section`)

Mesmo formato de `TestRenderSignupConfirm`: lockout de código (com corte de execução via `rerun_raises=True`), validação local, sucesso (grava `record_password_update`, avança pra `password_reset_success`) com falha não-propagante, os estados do resend (sucesso recente vs. genérico), clique em reenviar (sucesso e falha não-propagante), link de voltar ao login, e o subtítulo genérico quando não há e-mail em sessão.

## Casos de teste — `test_admin.py`

Duas técnicas novas de mock, específicas deste módulo:
- `_render_users_table` usa `st.components.v2.component(...)` (componente custom Shadow DOM) — os testes substituem `admin.st.components.v2.component` por uma fábrica fake que devolve um objeto (`_FakeComponentResult`) com os atributos `approve_<email>`/`revoke_<email>` que o código lê via `getattr(result, ...)`, simulando qual botão foi clicado sem precisar de um frontend real.
- `_render_confirm_dialog` é decorado com `@st.dialog(...)`, que levanta `StreamlitAPIException` se chamado fora de uma sessão real. Os testes chamam `admin._render_confirm_dialog.__wrapped__(pending)` — o `functools.wraps` do próprio Streamlit expõe a função original sem o decorator — e substituem `st.columns` por colunas fake (`_FakeColumn`, só com `.button()`) para simular clique em "Cancelar"/"Confirmar".

### `TestFormatDatetime` / `TestStatusLabel` / `TestRevokeKind` / `TestRevokeVisible` — Funções puras de rótulo/regra da tabela

| Teste | O que verifica |
|---|---|
| `test_valor_vazio_retorna_nunca` | `_format_datetime("")` → `"Nunca"` |
| `test_formata_timestamp_utc_para_horario_de_sao_paulo` | Timestamp ISO UTC convertido para `America/Sao_Paulo` (`DD/MM/AAAA HH:MM`) |
| `test_unconfirmed_retorna_inativo` / `test_pending_retorna_novo` / `test_active_habilitado_retorna_ativo` / `test_active_desabilitado_retorna_revogado` | `_status_label` mapeia `kind`/`enabled` para o rótulo em português certo |
| `test_pending_retorna_reject` / `test_unconfirmed_retorna_remove_unconfirmed` / `test_active_retorna_revoke` | `_revoke_kind` escolhe a ação de revogação certa por `kind` |
| `test_admin_nunca_e_revogavel` | Admin nunca tem botão de revogar, independente de `kind`/`enabled` |
| `test_pendente_nao_admin_e_revogavel` / `test_ativo_habilitado_nao_admin_e_revogavel` / `test_ativo_ja_desabilitado_nao_e_revogavel` | Regra de visibilidade do botão de revogar por combinação de `kind`/`enabled` |

### `TestBuildRows` / `TestBuildTableData` / `TestBuildTableHtml` / `TestBuildTableRowHtml` — Montagem da tabela

| Teste | O que verifica |
|---|---|
| `test_combina_e_marca_origem_das_3_listas` | `_build_rows` combina `list_pending_users`/`list_active_users`/`list_unconfirmed_users`, marcando `kind` e `is_admin` por linha |
| `test_ordena_pelo_sort_key_de_infrastructure_em_ordem_reversa` | `_build_rows` ordena pelo `admin_table_sort_key` de `infrastructure`, decrescente |
| `test_monta_colunas_em_portugues_com_status_e_datas_formatadas` / `test_nao_admin_gera_coluna_admin_nao` | `_build_table_data` traduz os campos do usuário pras colunas exibidas na tabela |
| `test_colgroup_reflete_as_larguras_configuradas` / `test_cabecalho_contem_todos_os_rotulos_de_coluna` / `test_colunas_centralizadas_ganham_classe_col_center` | `_build_table_html` monta `<colgroup>`/`<thead>` consistentes com `_COLUMN_WEIGHTS`/`_COLUMN_LABELS`/`_CENTERED_COLUMNS` |
| `test_linha_ativa_nao_admin_exibe_botao_de_revogar_sem_aprovar` / `test_linha_pendente_exibe_botao_de_aprovar_e_de_revogar` / `test_linha_admin_nunca_exibe_botao_de_revogar` | `_build_table_row_html` só inclui os botões que fazem sentido pra cada linha |
| `test_escapa_xss_no_email_e_no_nome` | Valores da linha passam por `html.escape` antes de entrar no HTML |
| `test_le_arquivo_estatico_real_de_admin_table` (`TestReadStatic`) | `_read_static` lê de verdade `static/css/admin_table.css` do disco |

### `TestRenderTable` / `TestQueuePendingAction` / `TestRenderUsersTable` — Orquestração da seção "Usuários"

| Teste | O que verifica |
|---|---|
| `test_sem_usuarios_exibe_mensagem_vazia` / `test_com_usuarios_chama_render_users_table` | `_render_table` alterna entre mensagem vazia e a tabela, conforme `_build_rows()` |
| `test_feedback_pendente_e_renderizado_e_removido_da_sessao` / `test_sem_feedback_pendente_nao_chama_render_feedback` | Mensagem de resultado da última ação (`admin_action_feedback`) aparece uma única vez |
| `test_grava_acao_pendente_e_chama_rerun` | `_queue_pending_action` grava `admin_pending_action` e força `st.rerun()` |
| `test_sem_clique_nao_enfileira_nenhuma_acao` | Resultado vazio do componente → nenhuma ação enfileirada |
| `test_clique_em_aprovar_enfileira_approve` / `test_clique_em_revogar_usuario_ativo_enfileira_revoke` / `test_clique_em_revogar_pendente_enfileira_reject` | Cada botão clicado no componente enfileira a ação certa |
| `test_acao_pendente_na_sessao_abre_dialogo_de_confirmacao` / `test_sem_acao_pendente_nao_abre_dialogo` | `_render_confirm_dialog` só é chamado quando há `admin_pending_action` na sessão |

### `TestRenderConfirmDialog` — Modal de confirmação (aprovar/reprovar/revogar/remover)

| Teste | O que verifica |
|---|---|
| `test_aprovar_confirmado_com_notificacao_enviada_com_sucesso` | Aprovar + notificar marcado → `approve_signup` + `notify_user_approved`, feedback de sucesso citando "e-mail enviado com sucesso" |
| `test_aprovar_confirmado_sem_marcar_notificar_nao_envia_email` | Notificar desmarcado → `notify_user_approved` nunca chamado, texto "e-mail não enviado (opção desmarcada)" |
| `test_reprovar_confirmado_com_falha_no_envio_de_email_gera_warning` | Falha ao notificar → `feedback["kind"] == "warning"` em vez de `"success"` |
| `test_remover_nao_confirmado_usa_mesmo_fluxo_de_reprovar` | `remove_unconfirmed` reaproveita `reject_signup`, com o rótulo "Cadastro não confirmado" |
| `test_revogar_confirmado_chama_revoke_access` | Revogar chama `revoke_access`/`notify_user_revoked`, rótulo "Acesso" |
| `test_cancelar_nao_chama_nenhuma_acao_de_infraestrutura` | Cancelar limpa `admin_pending_action` e fecha o modal sem chamar nenhuma API |
| `test_nenhum_botao_clicado_nao_faz_nada` | Sem clique em nenhum dos dois botões, nada muda (modal continua aberto) |

### `TestRenderAdminPanel` — Dispatch entre as 3 seções (Usuários/Perfil/Senha)

| Teste | O que verifica |
|---|---|
| `test_secao_padrao_usuarios_chama_render_table` | Seção padrão (`setdefault`) é `"usuarios"` |
| `test_secao_perfil_chama_render_profile_tab_com_proprio_perfil` | Seção "Perfil" reaproveita `render_profile_tab`/`get_own_profile` de `profile.py` para o próprio admin |
| `test_secao_senha_chama_render_password_tab` | Seção "Senha" reaproveita `render_password_tab` de `profile.py` |

## Casos de teste — `test_profile.py`

Fixture `autouse` própria (`_limpar_password_reauth_history`) limpa `profile._password_reauth_history` antes de cada teste — mesmo racional do `_limpar_cache_where` de `agent.py`, necessário porque é um dict `@st.cache_resource` (singleton vivo durante todo o processo pytest). `st.session_state` é substituído por um dict Python simples via `monkeypatch` em vez do `SessionStateProxy` real (que persiste entre testes no mesmo processo); `st.text_input`/`st.button` são substituídos por lambdas que retornam valores fixos por `key`, já que em modo bare (sem `streamlit run`) sempre ecoam o `value`/retornam `False`.

### `TestValidateNewPassword` — Validação local antes de chamar Cognito

| Teste | O que verifica |
|---|---|
| `test_campo_vazio_retorna_mensagem_de_preencher_tudo` | Qualquer um dos 3 campos vazio → "Preencha todos os campos." |
| `test_senhas_diferentes_retorna_mensagem_de_nao_coincidem` | Nova senha ≠ confirmação → "As senhas não coincidem." |
| `test_senha_fraca_delega_para_validate_password` | Delega para a política de senha compartilhada (`validate_password`, já testada em `test_components.py`) |
| `test_senha_valida_retorna_string_vazia` | Senha válida e confirmação igual → `""` |

### `TestGetOwnProfile`

| Teste | O que verifica |
|---|---|
| `test_retorna_perfil_quando_busca_tem_sucesso` | Retorna o dict de `infrastructure.get_user_profile` sem alteração |
| `test_retorna_fallback_quando_busca_falha` | `ClientError` → retorna `{"name": "", "email": email}` em vez de propagar |

### `TestRenderNavItem` / `TestRenderNavBar` — Barra horizontal de navegação (Perfil/Senha, reaproveitada por `admin.py`)

| Teste | O que verifica |
|---|---|
| `test_secao_inativa_sem_clique_nao_muda_estado_nem_chama_rerun` | Sem clique, nada muda |
| `test_secao_inativa_com_clique_ativa_e_chama_rerun` | Clique numa seção inativa grava `session_state[f"{scope}_active_section"]` e chama `st.rerun()` |
| `test_secao_ja_ativa_com_clique_nao_chama_rerun` | Clique numa seção já ativa não chama `st.rerun()` (guard `not is_active`) |
| `test_chama_render_nav_item_uma_vez_por_secao_com_o_scope_certo` | `render_nav_bar` chama `render_nav_item` uma vez por item de `_PROFILE_SECTIONS`, propagando o `scope` |

### `TestRenderProfileTab` — Aba "Perfil" (editar nome)

| Teste | O que verifica |
|---|---|
| `test_nome_inalterado_nao_chama_update_user_name_nem_feedback` | Nome igual ao atual → nenhuma chamada (branch `pass`) |
| `test_nome_em_branco_mostra_erro_sem_chamar_update_user_name` | Nome em branco → erro "O nome não pode ficar em branco." |
| `test_nome_alterado_chama_update_user_name_e_feedback_de_sucesso` | Nome novo → `infrastructure.update_user_name`, atualiza `session_state["user_name"]`, feedback de sucesso |
| `test_botao_nao_clicado_nao_chama_update_user_name_nem_feedback` | Sem clicar em "Salvar Perfil", nada acontece |

### `TestRenderPasswordTab` — Aba "Senha" (rate limiting + Cognito)

| Teste | O que verifica |
|---|---|
| `test_sem_bloqueio_e_sem_clique_nao_chama_change_password` | Estado inicial: sem chamada a Cognito, `locked_out=False` propagado ao script de gate do botão |
| `test_bloqueado_por_tentativas_mostra_aviso_e_nao_chama_change_password` | 3 tentativas na janela de 60s → aviso com countdown, `change_password` nunca chamado (independe do clique) |
| `test_validacao_local_falha_nao_chama_change_password` | Confirmação diferente da nova senha → erro local, sem chamar Cognito |
| `test_senha_atual_incorreta_registra_tentativa_e_mostra_erro` | `change_password` retorna `"invalid"` → registra timestamp em `_password_reauth_history` e mostra erro |
| `test_senha_atualizada_com_sucesso_limpa_campos_e_mostra_sucesso` | `change_password` retorna `"ok"` → chama `record_password_update`, limpa os 3 campos de `session_state`, feedback de sucesso |
| `test_falha_ao_gravar_password_updated_at_nao_impede_sucesso` | `record_password_update` levanta `ClientError` → não propaga, troca de senha ainda é reportada como sucesso ao usuário |

### `TestRenderProfilePanel` — Dispatch entre as duas abas

| Teste | O que verifica |
|---|---|
| `test_secao_padrao_perfil_chama_render_profile_tab` | Sem seção ativa em `session_state`, o padrão (`setdefault`) é `"perfil"` |
| `test_secao_senha_chama_render_password_tab` | Com `profile_active_section="senha"`, chama a aba de senha em vez da de perfil |

## Como executar

```bash
# Apenas os testes do lightsail
pytest test/lightsail_ia/ -v

# Com cobertura
pytest test/lightsail_ia/ --cov=app/lightsail_ia --cov-report=term-missing
```

## Cobertura mínima

**100%** — definido via `--cov-fail-under=100` no workflow de CI (`.github/workflows/test.yml`). Nenhum arquivo de `app/lightsail_ia/` está mais excluído dessa medição via `omit=` no `.coveragerc` — a lista de exclusão (que chegou a ter 6 arquivos: `app.py`, `forms.py`, `admin.py`, `recommendation.py`, `cards.py`, `profile.py`) foi encolhendo módulo a módulo conforme cada um ganhou testes, e `app.py` (o último, e o mais difícil — script de entrypoint sem nenhuma função isolada) saiu por último usando `streamlit.testing.v1.AppTest`. Todos os módulos de UI têm cobertura real (100%/99%+) via mock direto de `st.*` (`st.markdown`/`st.session_state`/`st.button`/`st.text_input`/`st.components.v2.component`/`st.fragment`/`st.rerun`/`st.columns`) — sem depender de um script Streamlit rodando de verdade — exceto `app.py`, que precisa do `AppTest` justamente por não ter função isolada pra chamar (ver `test_infrastructure.py`/`test_components.py`/`test_cards.py`/`test_profile.py`/`test_admin.py`/`test_forms.py`/`test_recommendation.py`/`test_app.py` acima).

## Observação sobre testes de interface

Não há mais nenhum módulo de interface do FilmBot fora do gate de cobertura — `app.py`, `forms.py`, `admin.py`, `recommendation.py`, `cards.py` e `profile.py` (a lista completa que um dia esteve em `omit=` no `.coveragerc`) têm todos teste automatizado hoje, cada um cobrindo o caso mais difícil da sua categoria: o componente Shadow DOM e o `@st.dialog` de `admin.py`; os blocos `@st.fragment(run_every=1)` aninhados de `forms.py`; a thread real via `ThreadPoolExecutor` + polling de `recommendation.py` (substituído por um `Future` fake); e o script de entrypoint sem função isolada de `app.py`, resolvido com `streamlit.testing.v1.AppTest` (framework novo pro projeto, já disponível via `streamlit==1.59.2`, sem precisar adicionar dependência — ver `test_app.py`, que também documenta uma limitação encontrada no mecanismo de alias `src.*` do `conftest.py` global). Para validar visualmente o app como um todo, além da suíte automatizada, ainda vale rodar localmente:

```bash
cd app/lightsail_ia
streamlit run app.py
```

A variável `CLOUDWATCH_LOG_GROUP` não é definida no conftest — isso é intencional: sem ela, o handler watchtower não é ativado e os testes rodam sem dependência do CloudWatch.

