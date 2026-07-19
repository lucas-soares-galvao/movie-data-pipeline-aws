# Testes — shared_src

## O que é testado

Testa as funções compartilhadas do pacote `shared_utils` (`app/shared_src/shared_utils/`), consumidas por `lambda_api`, `glue_etl`, `glue_details`, `glue_agg` e `glue_data_quality`: `api_get`/`get_api_secret` (`api_client.py`), `trigger_glue_job` (`triggers.py`), `get_resolved_option`/`configure_glue_logging` (`glue_helpers.py`), `translate_text` (`traducao_google.py`), `translate_text_aws` (`traducao_aws.py`), `resolve_translate_fn`/`translate_in_parallel`/`resolve_pt_translation`/`make_capped_fallback` (`traducao.py`, a fachada que reexporta as duas funções de serviço), `detect_language_langdetect` (`idioma_langdetect.py`), `detect_language_aws` (`idioma_aws.py`) e `resolve_detect_language_fn`/`add_detected_language_column` (`idioma.py`, fachada de detecção de idioma equivalente a `traducao.py`). Como o pacote não é instalado como dependência (é empacotado como wheel/zip apenas em deploy), `conftest.py` insere `app/shared_src` no `sys.path` para tornar `shared_utils` importável localmente. Todas as dependências externas (`requests`, `boto3`, `GoogleTranslator`, `getResolvedOptions`, `langdetect`) são substituídas por **mocks** (exceto em testes-smoke pontuais de detecção real de idioma), mantendo os testes rápidos, gratuitos e isolados.

## Estrutura

```
test/shared_src/
├── __init__.py
├── conftest.py             # sys.path + stub do módulo awsglue
├── requirements_tests.txt  # Dependências de teste (inclui langdetect)
├── test_api_client.py      # Testes de api_get e get_api_secret
├── test_glue_helpers.py    # Testes de get_resolved_option e configure_glue_logging
├── test_traducao_google.py # Testes de translate_text (Google Translate)
├── test_traducao_aws.py    # Testes de translate_text_aws (AWS Translate)
├── test_traducao.py        # Testes de resolve_translate_fn, translate_in_parallel, resolve_pt_translation e reuse_existing_translation
├── test_idioma_langdetect.py # Testes de detect_language_langdetect (langdetect, local)
├── test_idioma_aws.py      # Testes de detect_language_aws (AWS Comprehend)
├── test_idioma.py          # Testes de resolve_detect_language_fn e add_detected_language_column
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
| `test_retorna_chave_do_secrets_manager` | `boto3.client("secretsmanager")` chamado, `get_secret_value` chamado com o `SecretId` correto, e a chave certa extraída do JSON do segredo |

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

## Casos de teste — `test_traducao_google.py`

### `TestTranslateText`

`translate_text` sempre usa `GoogleTranslator(source="auto", target="pt")` — detecção
automática do idioma de origem — com até `_MAX_ATTEMPTS = 5` tentativas e backoff
(`time.sleep(attempt * 2)`), mas desiste mais cedo (`_MAX_ATTEMPTS_NO_ERROR = 2`)
quando o resultado vem idêntico ao original sem lançar exceção (indício de que não há
o que traduzir, e não de falha transitória).

| Teste | O que verifica |
|---|---|
| `test_retorna_string_vazia_para_entrada_vazia` | Texto `""` retorna `""` sem chamar o tradutor |
| `test_retorna_string_vazia_para_none` | Texto `None` retorna `""` sem chamar o tradutor |
| `test_traduz_texto_com_sucesso` | Tradução bem-sucedida retorna o texto traduzido e chama `translate` com o texto original |
| `test_retorna_original_apos_esgotar_tentativas` | Exceção em todas as `_MAX_ATTEMPTS` (5) tentativas faz a função retornar o texto original |
| `test_tenta_novamente_apos_excecao_e_depois_sucede` | Uma exceção seguida de sucesso: 2 chamadas ao tradutor, `time.sleep(2)` entre elas, retorna o texto traduzido |
| `test_tenta_novamente_quando_resultado_identico_ao_original` | Sem exceção, mas resultado igual ao original conta como tentativa falha e tenta de novo |
| `test_desiste_cedo_quando_sempre_identico_sem_excecao` | Resultado sempre idêntico ao original, sem exceção: desiste em `_MAX_ATTEMPTS_NO_ERROR` (2) tentativas, não nas 5 completas |
| `test_log_debug_quando_desiste_cedo_por_resultado_identico` | Esse desfecho (comum para nomes próprios/termos emprestados) loga em `DEBUG`, não `INFO` — não deve poluir o log padrão do workflow |
| `test_contador_de_resultado_identico_nao_precisa_ser_consecutivo` | O contador de tentativas "sem erro e resultado idêntico" soma o total mesmo com uma exceção intercalada, não exige consecutividade |
| `test_log_warning_em_caso_de_excecao` | Mensagem `"Falha ao traduzir"` aparece no log de warning quando a tradução falha |
| `test_contexto_aparece_no_log` | O parâmetro `context` aparece na mensagem de log de warning |
| `test_cria_translator_com_idiomas_corretos` | `GoogleTranslator` é instanciado com `source="auto", target="pt"` (detecção automática do idioma de origem) |

## Casos de teste — `test_traducao_aws.py`

### `TestTranslateTextAws`

Testa `translate_text_aws` via `boto3.client("translate")` mockado.

| Teste | O que verifica |
|---|---|
| `test_traduz_com_sucesso` | Chama `translate_text(Text=..., SourceLanguageCode="auto", TargetLanguageCode="pt")` e retorna `TranslatedText` |
| `test_retorna_original_em_caso_de_excecao` | Exceção (ex.: `boto3.client` falhando) retorna o texto original, sem propagar |
| `test_retorna_original_quando_resposta_vazia` | `TranslatedText` vazio retorna o texto original |
| `test_usa_region_default_us_east_1` | Sem `region` informado, usa `us-east-1` (default do parâmetro) — AWS Translate não está disponível em `sa-east-1`, região principal do pipeline |

## Casos de teste — `test_traducao.py`

### `TestResolveTranslateFn`

Resolve `"google"`/`"aws"` para uma função **composta primário+fallback** — o provider
escolhido (default `"google"` em todo o pipeline, `glue_details`/`glue_etl` via
EventBridge e os backfills manuais) é tentado primeiro; se falhar (resultado igual ao
texto original), o outro serviço é tentado automaticamente. Quando AWS Translate é o
fallback (`provider="google"`), as chamadas são limitadas por `aws_fallback_max_chars`
caracteres nesta execução (pago por caractere); quando é o primário (`provider="aws"`),
o fallback para Google não tem limite (grátis). `translate_google`/`translate_aws` são
parâmetros opcionais (default `translate_text`/`translate_text_aws`) para que um
chamador que faça patch da própria referência local (ex.:
`patch("src.utils.translate_text", ...)`) continue funcionando.

| Teste | O que verifica |
|---|---|
| `test_resolve_google_usa_google_como_primario` | `provider="google"` chama primeiro `translate_google` |
| `test_resolve_aws_usa_aws_como_primario` | `provider="aws"` chama primeiro `translate_aws` |
| `test_provider_invalido_levanta_value_error` | Qualquer valor fora de `"google"`/`"aws"` levanta `ValueError` |
| `test_usa_referencias_locais_informadas_pelo_chamador` | Passando `translate_google`/`translate_aws` explícitos, são exatamente essas referências (não as do módulo) que são chamadas |
| `test_fallback_disparado_quando_primario_falha` | Primário devolve o próprio texto (sinal de falha) — o fallback é chamado e seu resultado é devolvido |
| `test_fallback_nao_disparado_quando_primario_funciona` | Primário traduz com sucesso — fallback nunca é chamado |
| `test_texto_vazio_nao_dispara_fallback` | Texto vazio nunca aciona o fallback |
| `test_cap_por_caracteres_bloqueia_excedente` | `provider="google"`: o orçamento de caracteres do fallback (AWS) é consumido por chamada; texto que excederia o restante é pulado (devolve original) sem chamar o fallback |
| `test_cap_nao_se_aplica_quando_aws_e_primario` | `provider="aws"`: o fallback (Google) é chamado sem limite, mesmo com `aws_fallback_max_chars` pequeno |
| `test_cap_thread_safe_sob_concorrencia` | Disparado via `ThreadPoolExecutor`, o total de caracteres passados ao fallback nunca ultrapassa o orçamento (valida o lock) |

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
`"pt"`) marcada como concluída para sempre. Usada por `glue_details`,
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
| `test_esgota_tentativas_e_para_de_reenviar_ao_tradutor` | Ao atingir `max_tentativas`, a linha deixa de ser elegível mesmo com idioma do destino diferente de `"pt"` — protege contra retry infinito de conteúdo genuinamente não traduzível |
| `test_cria_coluna_tentativas_como_zero_quando_ausente` | Cria a coluna de tentativas como `0` quando ainda não existe no DataFrame |
| `test_only_missing_nao_recalcula_idioma_en_ja_preenchido` | Não redetecta o idioma da fonte quando a coluna já está preenchida (evita recomputar à toa em reruns) |
| `test_usa_max_workers_informado` | `max_workers` é repassado a `translate_in_parallel`, não hardcoded |

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

## Casos de teste — `test_idioma_langdetect.py`

### `TestDetectLanguageLangdetect`

`detect_language_langdetect` detecta o idioma (ISO 639-1) via `langdetect`, com
`DetectorFactory.seed = 0` fixado no import do módulo (sem isso, a amostragem
probabilística de n-gramas do `langdetect` pode devolver idiomas diferentes entre
execuções para o mesmo texto).

| Teste | O que verifica |
|---|---|
| `test_detecta_ingles` / `test_detecta_portugues` | Detecção correta para texto inequívoco (smoke test com `langdetect` real, sem mock) |
| `test_resultado_estavel_entre_chamadas_repetidas` | Regressão do seed fixo: o mesmo texto devolve sempre o mesmo idioma em chamadas repetidas |
| `test_texto_vazio_devolve_none_sem_chamar_detect` | Texto vazio devolve `None` sem invocar `detect` |
| `test_texto_so_espaco_devolve_none` | Texto só com espaços devolve `None` |
| `test_lang_detect_exception_capturada` | `LangDetectException` (comum em texto sem sinal linguístico, ex.: números) capturada, devolve `None` |
| `test_excecao_generica_capturada` | Qualquer outra exceção capturada, devolve `None` sem propagar |

## Casos de teste — `test_idioma_aws.py`

### `TestDetectLanguageAws`

`detect_language_aws` chama `boto3.client("comprehend").detect_dominant_language`,
devolvendo o `LanguageCode` de maior `Score`. Mesmo padrão defensivo de
`translate_text_aws` — nunca lança exceção.

| Teste | O que verifica |
|---|---|
| `test_detecta_com_sucesso_idioma_de_maior_score` | Entre múltiplos idiomas na resposta, devolve o de maior `Score` |
| `test_usa_region_default_us_east_1` | Sem `region` informado, usa `us-east-1` — Comprehend não está em `sa-east-1` |
| `test_lista_de_idiomas_vazia_devolve_none` | Resposta sem `Languages` devolve `None` |
| `test_excecao_capturada_devolve_none` | Exceção (ex.: `boto3.client` falhando) devolve `None`, sem propagar |
| `test_texto_vazio_devolve_none_sem_chamar_boto3` / `test_texto_so_espaco_devolve_none` | Texto vazio/só espaço devolve `None` sem sequer chamar `boto3.client` |

## Casos de teste — `test_idioma.py`

### `TestResolveDetectLanguageFn`

Compõe detecção local (`langdetect`) primeiro; se devolver `None`, cai para AWS
Comprehend, capado por `aws_fallback_max_chars` caracteres via `make_capped_fallback`
(mesmo mecanismo de orçamento do fallback de tradução).

| Teste | O que verifica |
|---|---|
| `test_usa_local_quando_local_detecta` | Detecção local com sucesso não aciona o AWS |
| `test_cai_para_aws_quando_local_devolve_none` | Local devolve `None` → cai para AWS |
| `test_aws_nao_e_chamado_quando_local_detecta` | Confirma que a função AWS nunca é invocada quando o local já resolve |
| `test_orcamento_esgotado_devolve_none_sem_chamar_aws` | Orçamento de caracteres esgotado devolve `None` sem chamar o AWS |
| `test_orcamento_suficiente_permite_fallback_aws` | Orçamento suficiente permite o fallback normalmente |

### `TestAddDetectedLanguageColumn`

| Teste | O que verifica |
|---|---|
| `test_aplica_detect_fn_a_cada_linha` | Aplica `detect_fn` a cada valor da coluna fonte, gravando na coluna de destino |
| `test_nan_tratado_como_string_vazia` | `NaN`/`None` na coluna fonte é tratado como string vazia antes de chamar `detect_fn` |
| `test_default_detect_fn_usado_quando_nao_informado` | Sem `detect_fn` explícito, usa `resolve_detect_language_fn()` (langdetect real) |
| `test_modifica_df_in_place_e_retorna_mesma_referencia` | Modifica o DataFrame in-place e retorna a mesma referência |
| `test_only_missing_false_recalcula_todas_as_linhas` | `only_missing=False` (default) recalcula todas as linhas, mesmo já preenchidas — comportamento idêntico ao anterior |
| `test_only_missing_true_preserva_linhas_ja_preenchidas` | `only_missing=True` só detecta onde a coluna de destino ainda está vazia/nula |
| `test_only_missing_true_cria_coluna_ausente_e_detecta_tudo` | `only_missing=True` com a coluna de destino ainda ausente detecta todas as linhas normalmente |

## Como executar

```bash
# Apenas os testes do shared_src
pytest test/shared_src/ -v

# Com cobertura
pytest test/shared_src/ --cov=app/shared_src --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).
