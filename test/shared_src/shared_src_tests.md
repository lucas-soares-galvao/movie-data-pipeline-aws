# Testes — shared_src

## O que é testado

Testa as funções compartilhadas do pacote `shared_utils` (`app/shared_src/shared_utils/`), consumidas por `lambda_api`, `lambda_cognito_email_sender`, `lightsail_ia`, `glue_etl`, `glue_details`, `glue_agg` e `glue_data_quality`: `api_get`/`get_api_secret` (`api_client.py`), `trigger_glue_job` (`triggers.py`), `get_resolved_option`/`configure_glue_logging` (`glue_helpers.py`), `load_gmail_credentials`/`send_gmail_email` (`gmail_helpers.py`), `load_llm_api_key` (`llm_client.py`), `translate_text_llm` (`traducao_llm.py`), `translate_in_parallel`/`resolve_pt_translation`/`reuse_existing_translation` (`traducao.py`, a fachada que orquestra elegibilidade/cache/paralelismo em torno do serviço de tradução), `detect_language_llm` (`idioma_llm.py`) e `add_detected_language_column` (`idioma.py`, fachada de detecção de idioma equivalente a `traducao.py`). Como o pacote não é instalado como dependência (é empacotado como wheel/zip apenas em deploy), `conftest.py` insere `app/shared_src` no `sys.path` para tornar `shared_utils` importável localmente. Todas as dependências externas (`requests`, `boto3`, `smtplib`, `litellm.completion`, `getResolvedOptions`) são substituídas por **mocks** — nenhum teste chama a rede de verdade (bloqueado por `test/conftest.py`).

## Estrutura

```
test/shared_src/
├── __init__.py
├── conftest.py             # sys.path + stub do módulo awsglue
├── requirements_tests.txt  # Dependências de teste (inclui litellm)
├── test_api_client.py      # Testes de api_get e get_api_secret
├── test_s3_helpers.py      # Testes de expected_bucket_owner_kwargs (ExpectedBucketOwner)
├── test_glue_helpers.py    # Testes de get_resolved_option e configure_glue_logging
├── test_gmail_helpers.py   # Testes de load_gmail_credentials e send_gmail_email
├── test_llm_client.py      # Testes de load_llm_api_key (chave do LLM via Secrets Manager/ambiente)
├── test_traducao_llm.py    # Testes de translate_text_llm (LLM via OpenRouter)
├── test_traducao.py        # Testes de _is_google_error_page, translate_in_parallel, resolve_pt_translation e reuse_existing_translation
├── test_idioma_llm.py      # Testes de detect_language_llm (LLM via OpenRouter)
├── test_idioma.py          # Testes de add_detected_language_column
└── test_triggers.py        # Testes de trigger_glue_job
```

## Fixtures (`conftest.py`)

`conftest.py` não expõe fixtures pytest — executa duas ações de setup no import:

| Ação | Descrição |
|---|---|
| `sys.path.insert` | Adiciona `app/shared_src` ao `sys.path` para permitir `from shared_utils import ...` sem instalar o wheel |
| Stub de `awsglue` | Registra `awsglue`/`awsglue.utils` em `sys.modules` com `getResolvedOptions` como `MagicMock`, já que o SDK real só existe no runtime do Glue — necessário para `glue_helpers.py` ser importável |

## Casos de teste — `test_api_client.py`

### `TestApiGet`

| Teste | O que verifica |
|---|---|
| `test_retorna_json_em_sucesso` | Resposta 200 retorna o JSON imediatamente, sem `time.sleep` |
| `test_retry_em_status_transiente_e_retorna_em_sucesso` | 500 seguido de 200: uma nova tentativa e retorno correto |
| `test_retry_em_429_usa_retry_after` | 429 com header `Retry-After: 5` faz o wait respeitar esse valor (`wait >= 5`) |
| `test_retry_em_connection_error_e_retorna_em_sucesso` | `ConnectionError` seguido de sucesso: retry e retorno correto |
| `test_levanta_apos_esgotar_tentativas_http` | 500 em todas as tentativas levanta `HTTPError` após `max_retries` (5) chamadas |
| `test_levanta_apos_esgotar_tentativas_connection` | `ConnectionError` em todas as tentativas propaga a exceção após 5 chamadas |

### `TestGetApiSecret`

| Teste | O que verifica |
|---|---|
| `test_retorna_chave_do_secrets_manager` | `boto3.client("secretsmanager", config=...)` chamado (com `config` de timeout explícito), `get_secret_value` chamado com o `SecretId` correto, e a chave certa extraída do JSON do segredo. Mocka `boto3.client` (objeto global) e não `shared_utils.api_client.boto3` — o `conftest.py` de `test/` apaga `shared_utils.*` de `sys.modules` ao coletar suites de `_SUITE_TO_APP`, então o patch por string poderia resolver o módulo reimportado enquanto a função executada é a referência do módulo antigo, deixando o `boto3` real vazar e tentar credenciais AWS de verdade |

## Casos de teste — `test_s3_helpers.py`

### `TestExpectedBucketOwnerKwargs`

`expected_bucket_owner_kwargs` devolve o kwarg `ExpectedBucketOwner` a espalhar (`**`) nas
chamadas boto3 ao S3, a partir de `AWS_ACCOUNT_ID`. Lê a variável a cada chamada (não cacheia
no import) porque, nos jobs Glue, ela só é publicada em `os.environ` dentro de
`get_parameters_glue`, depois do import do módulo.

| Teste | O que verifica |
|---|---|
| `test_retorna_kwarg_quando_aws_account_id_definida` | Com `AWS_ACCOUNT_ID` definida, devolve `{"ExpectedBucketOwner": <id>}` |
| `test_retorna_vazio_quando_aws_account_id_ausente` | Sem a variável, devolve `{}` |
| `test_retorna_vazio_quando_aws_account_id_vazia` | String vazia é tratada como ausente (evita `ExpectedBucketOwner=""` inválido no boto3) |
| `test_le_valor_a_cada_chamada_nao_no_import` | O valor não é cacheado — reflete a variável corrente a cada chamada |

## Casos de teste — `test_triggers.py`

### `TestTriggerGlueJob`

| Teste | O que verifica |
|---|---|
| `test_calls_start_job_run_with_job_name` | Sem kwargs, `start_job_run` é chamado com `Arguments={}` |
| `test_converts_kwargs_to_glue_arguments` | Kwargs são convertidos para o formato `--CHAVE` |
| `test_omits_none_values` | Kwargs com valor `None` são omitidos de `Arguments` |
| `test_includes_year_when_provided` | Kwarg com valor não-`None` é incluído normalmente |
| `test_returns_job_run_id` | Retorna o `JobRunId` da resposta mockada |
| `test_passes_all_details_arguments` | Múltiplos argumentos (`MEDIA_TYPE`, `YEAR`, `END_YEAR`, `DATABASE`) são todos convertidos corretamente |

## Casos de teste — `test_glue_helpers.py`

### `TestGetResolvedOption`

| Teste | O que verifica |
|---|---|
| `test_delega_para_getResolvedOptions` | Delega para `getResolvedOptions(sys.argv, args)` e repassa o resultado |
| `test_repassa_lista_vazia` | Lista de argumentos vazia é repassada sem erro |
| `test_propaga_excecao_de_argumento_ausente` | `SystemExit` levantado por `getResolvedOptions` (argumento obrigatório ausente) é propagado |

### `TestConfigureGlueLogging`

| Teste | O que verifica |
|---|---|
| `test_retorna_logger` | Retorna uma instância de `logging.Logger` |
| `test_configura_nivel_info` | Nível do logger raiz é configurado como `INFO` |
| `test_handler_escreve_em_stdout` | Existe um handler cujo stream é `sys.stdout` |

## Casos de teste — `test_gmail_helpers.py`

Compartilhado entre `lambda_cognito_email_sender` (trigger `CustomEmailSender` do
Cognito) e `lightsail_ia` (notificação de aprovação/reprovação/revogação de acesso,
`src/infrastructure.py`) — os testes de integração de cada chamador (que o e-mail
certo é montado e enviado) continuam em `test/lambda_cognito_email_sender/test_main.py`
e `test/lightsail_ia/test_infrastructure.py`; aqui cobre só as duas funções em si.

### `TestLoadGmailCredentials`

| Teste | O que verifica |
|---|---|
| `test_busca_credenciais_do_secrets_manager` | Com `FILMBOT_SECRET_ARN` definida, busca `gmail_sender_email`/`gmail_app_password` no Secrets Manager |
| `test_cai_para_fallback_de_env_vars_quando_secret_arn_nao_configurado` | Sem `FILMBOT_SECRET_ARN`, usa `GMAIL_SENDER_EMAIL`/`GMAIL_APP_PASSWORD` sem chamar `boto3.client` |
| `test_cai_para_fallback_quando_secret_nao_tem_as_chaves_gmail` | Secret existe mas sem as chaves `gmail_*` — cai para o fallback de env vars |
| `test_retorna_none_quando_nenhuma_credencial_esta_configurada` | Nenhuma das duas fontes configurada retorna `None` |

### `TestSendGmailEmail`

| Teste | O que verifica |
|---|---|
| `test_envia_email_com_sucesso` | Monta a mensagem (Subject/From/To) e chama `smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=_SMTP_TIMEOUT_SECONDS)` |
| `test_retorna_false_sem_chamar_smtp_quando_nenhuma_credencial_esta_configurada` | Sem credenciais, retorna `False` sem sequer chamar `SMTP_SSL` |
| `test_loga_erro_sem_propagar_quando_smtp_falha` | Falha de conexão SMTP é logada e retorna `False`, nunca propaga |

## Casos de teste — `test_llm_client.py`

### `TestLoadLlmApiKey`

`load_llm_api_key(secret_field, env_var, region="sa-east-1", required=True)` busca uma
chave de API de LLM do secret unificado (`FILMBOT_SECRET_ARN`) ou de uma variável de
ambiente — compartilhada entre o agente de recomendação (`lightsail_ia`) e a tradução
via LLM (`traducao_llm.py`/`idioma_llm.py`).

| Teste | O que verifica |
|---|---|
| `test_campo_obrigatorio_vem_do_secrets_manager_quando_arn_configurado` | Com `FILMBOT_SECRET_ARN` definida, busca o campo no secret via `boto3.client("secretsmanager", region_name=...)` |
| `test_campo_obrigatorio_vem_do_ambiente_sem_arn` | Sem `FILMBOT_SECRET_ARN`, usa a env var informada, sem chamar `boto3.client` |
| `test_campo_opcional_presente_no_secret` | `required=False` com o campo presente no secret devolve o valor |
| `test_campo_opcional_ausente_no_secret_retorna_none_sem_derrubar_o_chamador` | `required=False` com o campo ausente no secret devolve `None` (`.get()`, não indexação direta) |
| `test_campo_opcional_vem_do_ambiente_sem_arn` | `required=False` sem `FILMBOT_SECRET_ARN` usa a env var |
| `test_campo_obrigatorio_ausente_no_secret_levanta_key_error` | `required=True` (default) com o campo ausente no secret levanta `KeyError` |
| `test_nenhuma_fonte_configurada_devolve_none` | Sem `FILMBOT_SECRET_ARN` nem a env var, devolve `None` |
| `test_regiao_customizada_repassada_ao_client` | `region` é repassado ao `boto3.client` |

## Casos de teste — `test_traducao_llm.py`

### `TestTranslateTextLlm`

`translate_text_llm(text)` traduz via LLM (OpenRouter, `litellm.completion`), com
fallback nativo de modelo (`extra_body.models`) se o primário falhar. Nunca lança
exceção — mesmo contrato do antigo `translate_text_aws`.

| Teste | O que verifica |
|---|---|
| `test_texto_vazio_nao_chama_api` / `test_none_nao_chama_api` | Texto vazio/`None` devolve `""` sem chamar `litellm.completion` |
| `test_traduz_com_sucesso` | Resposta mockada com o texto traduzido é devolvida |
| `test_excecao_na_chamada_devolve_original` | Exceção na chamada (rede, timeout, 401/402/429) devolve o texto original |
| `test_content_vazio_devolve_original` / `test_content_none_devolve_original` / `test_content_so_espacos_devolve_original` | Resposta vazia/`None`/só espaços devolve o texto original |
| `test_resultado_igual_ao_original_e_devolvido_mesmo_assim` | Nome próprio/termo sem tradução — o LLM pode ecoar o original de propósito; quem decide o que fazer com isso é `resolve_pt_translation`, não esta função |
| `test_remove_aspas_ao_redor_do_resultado` / `test_remove_cerca_de_markdown_ao_redor_do_resultado` | Limpeza defensiva de aspas/cercas de markdown que o modelo eventualmente envolva ao redor do resultado |
| `test_passa_modelo_e_chave_configurados` | Chama com `model="openrouter/qwen/qwen3.8-flash"` (default) e `temperature=0` |
| `test_repassa_fallback_de_modelo_no_extra_body` | `extra_body.models=["deepseek/deepseek-v4.1-flash"]` (default) e `extra_body.reasoning={"enabled": False}` |
| `test_mensagem_do_usuario_e_o_proprio_texto` | A última mensagem é `{"role": "user", "content": text}`, a primeira é `system` |

## Casos de teste — `test_idioma_llm.py`

### `TestDetectLanguageLlm`

`detect_language_llm(text)` detecta o idioma (ISO 639-1) via LLM (OpenRouter),
reaproveitando modelo/chave/fallback de `traducao_llm.py`. Nunca lança exceção —
texto vazio, falha na chamada, ou resposta fora do padrão `^[a-z]{2}$` devolvem `None`.

| Teste | O que verifica |
|---|---|
| `test_texto_vazio_devolve_none_sem_chamar_api` / `test_texto_so_espacos_devolve_none_sem_chamar_api` | Texto vazio/só espaços devolve `None` sem chamar `litellm.completion` |
| `test_detecta_com_sucesso` | Resposta mockada com o código devolve esse código |
| `test_normaliza_maiusculas` / `test_remove_espacos_ao_redor_do_codigo` | `"EN"`/`" pt "` são normalizados para `"en"`/`"pt"` |
| `test_excecao_na_chamada_devolve_none` / `test_content_none_devolve_none` | Falha na chamada ou resposta vazia devolve `None` |
| `test_codigo_fora_do_padrao_iso_639_1_devolve_none` / `test_codigo_com_numero_devolve_none` | Resposta fora do formato esperado (frase, código com número) devolve `None` — nunca propaga um valor inválido para `detected_language_*_column` |
| `test_loga_warning_para_codigo_fora_do_padrao` | Loga `WARNING` com o conteúdo recebido quando a resposta não bate o padrão |
| `test_passa_modelo_e_chave_configurados` / `test_repassa_fallback_de_modelo_no_extra_body` | Mesmo modelo/fallback de `translate_text_llm` |

## Casos de teste — `test_traducao.py`

### `TestIsGoogleErrorPage`

`_is_google_error_page` (função privada) higieniza dado **legado**: a página de erro do
Google (`Error <status> (<motivo>)!!<n>`) que versões anteriores do código — de antes da
migração para LLM — gravavam como se fosse a tradução (ver `GOOGLE_ERROR_PAGE`, texto
real observado no dev).

| Teste | O que verifica |
|---|---|
| `test_casa_o_texto_de_erro_real_observado` | O texto real encontrado nas tabelas do dev (`Error 500 (Server Error)!!1500.That’s an error...`) é reconhecido |
| `test_casa_outro_status_http` | O padrão vale para outro status (`Error 404 (Not Found)!!1...`) |
| `test_nao_casa_traducao_normal_nem_prefixo_incompleto` | Parametrizado: tradução normal, `""`, `"Error"`, `"Error 500"` e `"Erro 500 (Server Error)!!1"` (pt) não casam |
| `test_nao_casa_quando_erro_aparece_so_no_meio_do_texto` | Regex ancorada no início: "Error 500..." no meio do texto não casa |
| `test_nao_string_devolve_false` | Parametrizado: `None`, NaN, `int` e `list` devolvem `False` (valor vem de coluna de DataFrame) |

### `TestTranslateInParallel`

| Teste | O que verifica |
|---|---|
| `test_traduz_cada_valor_e_preserva_a_ordem` | Aplica `translate_fn` a cada valor via `ThreadPoolExecutor`, preservando a ordem de entrada |
| `test_lista_vazia_nao_chama_traduzir_fn` | Lista vazia retorna `[]` sem chamar `translate_fn` |
| `test_usa_max_workers_informado` | `max_workers` é repassado ao `ThreadPoolExecutor`, não hardcoded |

### `TestResolvePtTranslation`

Sincroniza a coluna de tradução (`target_column`, já inicializada pelo chamador) com a
fonte: detecta o idioma da fonte e do resultado (só onde ainda vazio), copia a fonte
direto quando ela já é `"pt"` (sem chamar tradutor), traduz as linhas elegíveis (fonte
preenchida, idioma do resultado ainda diferente de `"pt"`, tentativas abaixo do teto),
incrementa o contador de tentativas e redetecta o idioma do resultado só nas linhas
recém-traduzidas. Basear a elegibilidade no idioma real do resultado — em vez da antiga
heurística de string-diff — evita tanto retraduzir o que já está correto quanto deixar
uma mistradução silenciosa (resultado diferente da fonte, mas em outro idioma que não
`"pt"`) marcada como concluída para sempre. Se `needs_translation_column` for informado,
grava também um booleano com "fonte preenchida E idioma do resultado != `pt`" — mesmo
critério da elegibilidade, mas sem o teto de tentativas, refletindo o estado atual do
dado mesmo quando o pipeline já desistiu de retentar. Usada por `glue_details`,
`scripts/backfill_traducao.py` e `glue_etl` (`name_pt` de países/idiomas) em vez de cada
um manter sua própria cópia da orquestração.

| Teste | O que verifica |
|---|---|
| `test_traduz_registros_elegiveis_pendentes` | Traduz todos os registros elegíveis, gravando na coluna de destino |
| `test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_tradutor` | Fonte já detectada como `"pt"` é copiada direto para o destino, sem chamar `translate_fn`, e o idioma do resultado é marcado `"pt"` diretamente |
| `test_elegibilidade_usa_idioma_do_destino_nao_diff_de_string` | Um destino que difere da fonte mas cujo idioma detectado não é `"pt"` (mistradução silenciosa) continua elegível — diferente da antiga heurística de string-diff |
| `test_nao_retraduz_quando_idioma_pt_ja_confirmado` | Destino cujo idioma já é `"pt"` não é reenviado ao tradutor |
| `test_redetecta_idioma_pt_so_nas_linhas_recem_traduzidas` | A detecção do idioma do destino feita antes da tradução (sobre o valor antigo/vazio) é substituída só nas linhas efetivamente traduzidas nesta execução |
| `test_incrementa_tentativas_para_linhas_elegiveis` | O contador de tentativas sobe 1 a cada execução para linhas elegíveis, mesmo quando a tradução falha |
| `test_copia_direta_nao_incrementa_tentativas` | A cópia direta (fonte já `"pt"`) não conta como tentativa |
| `test_esgota_tentativas_e_para_de_reenviar_ao_tradutor` | Ao atingir `max_attempts`, a linha deixa de ser elegível mesmo com idioma do destino diferente de `"pt"` — protege contra retry infinito de conteúdo genuinamente não traduzível (relevante também porque o LLM não é determinístico) |
| `test_cria_coluna_tentativas_como_zero_quando_ausente` | Cria a coluna de tentativas como `0` quando ainda não existe no DataFrame |
| `test_only_missing_nao_recalcula_idioma_en_ja_preenchido` | Não redetecta o idioma da fonte quando a coluna já está preenchida (evita recomputar à toa em reruns) |
| `test_usa_max_workers_informado` | `max_workers` é repassado a `translate_in_parallel`, não hardcoded |
| `test_precisa_traducao_column_none_nao_cria_coluna` | Parâmetro `needs_translation_column` omitido (`None`, default) não cria coluna nova no DataFrame |
| `test_precisa_traducao_true_quando_resultado_ainda_nao_e_pt` | Fonte preenchida e idioma do resultado ainda diferente de `"pt"` após a tentativa de tradução → `True` |
| `test_precisa_traducao_false_quando_resultado_ja_e_pt` | Fonte já detectada como `"pt"` (cópia direta) → `False` |
| `test_precisa_traducao_false_quando_fonte_vazia` | Fonte vazia/nula → `False` (nada a traduzir) |
| `test_precisa_traducao_continua_true_mesmo_com_tentativas_esgotadas` | Diferente da elegibilidade, continua `True` mesmo após `translation_attempts_column` atingir `max_attempts` — reflete o estado atual do dado, não se o pipeline ainda vai retentar |
| `test_descarta_pagina_de_erro_do_google_e_retraduz` | Passo 0: destino com a página de erro histórica do Google é limpo, tem idioma detectado zerado e é retraduzido (contador zerado e incrementado pela nova tentativa) |
| `test_pagina_de_erro_com_tentativas_esgotadas_volta_a_ser_elegivel` | O ponto do auto-reparo: mesmo com `translation_attempts >= max_attempts`, a linha com página de erro volta a ser elegível (contador zerado) |
| `test_pagina_de_erro_que_falha_de_novo_fica_vazia_e_nao_com_o_texto_de_erro` | Se a retradução também falhar (tradutor devolve o original), o destino fica com o original e nunca volta com a página de erro |
| `test_nao_toca_em_destinos_que_nao_sao_pagina_de_erro` | Só a linha poluída é retraduzida; a tradução válida e o contador da outra linha ficam intactos |
| `test_loga_quantidade_de_paginas_de_erro_descartadas` / `test_sem_pagina_de_erro_nao_loga_descarte` | Log INFO com a quantidade descartada; nenhum log quando não há página de erro |
| `test_loga_resumo_agregado_de_falhas_de_traducao` | Resumo agregado ("N falha(s) / M elegível(is)") em INFO, não uma linha por registro |

### `TestReuseExistingTranslation`

Pré-preenche a coluna de destino com a tradução já persistida (`previous_df`) quando a
coluna fonte não mudou para o mesmo `key_column` (default `"id"`) — evita retraduzir
texto idêntico ao da última execução. Não sobrescreve valor já preenchido no `df` novo
(preserva prioridade da tradução nativa do TMDB). Usada por `glue_details`
(`key_column="id"`) e `glue_etl` (`key_column="iso_3166_1"`/`"iso_639_1"`, tabela
`configuration`).

| Teste | O que verifica |
|---|---|
| `test_reaproveita_quando_fonte_identica` | Reaproveita a coluna de destino de `previous_df` quando a fonte é idêntica para a mesma chave |
| `test_nao_reaproveita_quando_fonte_mudou` | Não reaproveita quando a fonte mudou em relação a `previous_df` |
| `test_nao_reaproveita_id_novo_sem_historico` | Não reaproveita quando a chave não existe em `previous_df` |
| `test_df_anterior_none_nao_quebra` | `previous_df=None` não lança exceção e não altera `df` |
| `test_df_anterior_vazio_nao_quebra` | `previous_df` vazio não lança exceção e não altera `df` |
| `test_nao_sobrescreve_destino_ja_preenchido` | Não sobrescreve a coluna de destino já preenchida no `df` novo |
| `test_ignora_schema_antigo_sem_coluna` | `previous_df` sem a coluna de destino (schema antigo) não lança exceção e não reaproveita |
| `test_ids_duplicados_no_df_anterior_usa_ultimo` | Com chaves duplicadas em `previous_df`, usa o último valor |
| `test_coluna_chave_customizada` | Funciona com `key_column="iso_3166_1"` (caso de uso do `glue_etl`) |
| `test_coluna_chave_customizada_nao_reaproveita_quando_ausente_no_anterior` | Chave customizada ausente em `previous_df` não reaproveita |
| `test_reuse_existing_translation_ainda_reaproveita_pagina_de_erro_do_cache` | Contrato documentado: o cache não filtra a página de erro — quem a descarta é o passo 0 de `resolve_pt_translation` |

## Casos de teste — `test_idioma.py`

### `TestAddDetectedLanguageColumn`

| Teste | O que verifica |
|---|---|
| `test_aplica_detect_fn_a_cada_linha` | Aplica `detect_fn` a cada valor da coluna fonte, gravando na coluna de destino |
| `test_nan_tratado_como_string_vazia` | `NaN`/`None` na coluna fonte é tratado como string vazia antes de chamar `detect_fn` |
| `test_default_detect_fn_usado_quando_nao_informado` | Sem `detect_fn` explícito, usa `detect_language_llm` (mockado via `new=` — ver nota abaixo) |
| `test_modifica_df_in_place_e_retorna_mesma_referencia` | Modifica o DataFrame in-place e retorna a mesma referência |
| `test_only_missing_false_recalcula_todas_as_linhas` | `only_missing=False` (default) recalcula todas as linhas, mesmo já preenchidas — comportamento idêntico ao anterior |
| `test_only_missing_true_preserva_linhas_ja_preenchidas` | `only_missing=True` só detecta onde a coluna de destino ainda está vazia/nula |
| `test_only_missing_true_cria_coluna_ausente_e_detecta_tudo` | `only_missing=True` com a coluna de destino ainda ausente detecta todas as linhas normalmente |

**Nota sobre mock de `detect_fn`/`translate_fn` passados a `.apply()`:** `pandas.Series.apply`
trata um `unittest.mock.Mock`/`MagicMock` como *list-like* (por configurar `__iter__` por
padrão) e tenta uma agregação em vez de chamar a função por elemento — gera
`ValueError: No objects to concatenate`. Qualquer teste que mocke uma função destinada a
`.apply()` (detecção, nunca tradução — que usa `ThreadPoolExecutor.map`, imune a esse
problema) precisa usar `patch(..., new=<função simples>)`, nunca `side_effect=`/
`return_value=` (que deixam o objeto como `Mock`).

## Como executar

```bash
# Apenas os testes do shared_src
pytest test/shared_src/ -v

# Com cobertura
pytest test/shared_src/ --cov=app/shared_src --cov-report=term-missing
```

## Cobertura mínima

**100%** — definido via `--cov-fail-under=100` no workflow de CI (`.github/workflows/test.yml`).
