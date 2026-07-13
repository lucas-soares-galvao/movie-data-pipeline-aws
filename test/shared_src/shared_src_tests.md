# Testes — shared_src

## O que é testado

Testa as funções compartilhadas do pacote `shared_utils` (`app/shared_src/shared_utils/`), consumidas por `lambda_api`, `glue_etl`, `glue_details`, `glue_agg` e `glue_data_quality`: `api_get`/`get_api_secret` (`api_client.py`), `trigger_glue_job` (`triggers.py`), `get_resolved_option`/`configurar_logging_glue` (`glue_helpers.py`), `traduzir_texto` (`traducao_google.py`), `traduzir_texto_aws` (`traducao_aws.py`) e `resolver_traduzir_fn`/`traduzir_em_paralelo`/`traduzir_coluna_pendente`/`elegivel_overview_pt`/`elegivel_tagline_pt`/`elegivel_keywords_pt` (`traducao.py`, a fachada que reexporta as duas funções de serviço). Como o pacote não é instalado como dependência (é empacotado como wheel/zip apenas em deploy), `conftest.py` insere `app/shared_src` no `sys.path` para tornar `shared_utils` importável localmente. Todas as dependências externas (`requests`, `boto3`, `GoogleTranslator`, `getResolvedOptions`) são substituídas por **mocks**, mantendo os testes rápidos, gratuitos e isolados.

## Estrutura

```
test/shared_src/
├── __init__.py
├── conftest.py             # sys.path + stub do módulo awsglue
├── requirements_tests.txt  # Dependências de teste
├── test_api_client.py      # Testes de api_get e get_api_secret
├── test_glue_helpers.py    # Testes de get_resolved_option e configurar_logging_glue
├── test_traducao_google.py # Testes de traduzir_texto (Google Translate)
├── test_traducao_aws.py    # Testes de traduzir_texto_aws (AWS Translate)
├── test_traducao.py        # Testes de resolver_traduzir_fn, traduzir_em_paralelo, traduzir_coluna_pendente e das máscaras elegivel_*
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

### `TestConfigurarLoggingGlue`

| Teste | O que verifica |
|---|---|
| `test_retorna_logger` | Retorna uma instância de `logging.Logger` |
| `test_configura_nivel_info` | Nível do logger raiz é configurado como `INFO` |
| `test_handler_escreve_em_stdout` | Existe um handler cujo stream é `sys.stdout` |

## Casos de teste — `test_traducao_google.py`

### `TestTraduzirTexto`

`traduzir_texto` sempre usa `GoogleTranslator(source="auto", target="pt")` — detecção
automática do idioma de origem — com até `_MAX_TENTATIVAS = 5` tentativas e backoff
(`time.sleep(tentativa * 2)`), mas desiste mais cedo (`_MAX_TENTATIVAS_SEM_ERRO = 2`)
quando o resultado vem idêntico ao original sem lançar exceção (indício de que não há
o que traduzir, e não de falha transitória).

| Teste | O que verifica |
|---|---|
| `test_retorna_string_vazia_para_entrada_vazia` | Texto `""` retorna `""` sem chamar o tradutor |
| `test_retorna_string_vazia_para_none` | Texto `None` retorna `""` sem chamar o tradutor |
| `test_traduz_texto_com_sucesso` | Tradução bem-sucedida retorna o texto traduzido e chama `translate` com o texto original |
| `test_retorna_original_apos_esgotar_tentativas` | Exceção em todas as `_MAX_TENTATIVAS` (5) tentativas faz a função retornar o texto original |
| `test_tenta_novamente_apos_excecao_e_depois_sucede` | Uma exceção seguida de sucesso: 2 chamadas ao tradutor, `time.sleep(2)` entre elas, retorna o texto traduzido |
| `test_tenta_novamente_quando_resultado_identico_ao_original` | Sem exceção, mas resultado igual ao original conta como tentativa falha e tenta de novo |
| `test_desiste_cedo_quando_sempre_identico_sem_excecao` | Resultado sempre idêntico ao original, sem exceção: desiste em `_MAX_TENTATIVAS_SEM_ERRO` (2) tentativas, não nas 5 completas |
| `test_log_debug_quando_desiste_cedo_por_resultado_identico` | Esse desfecho (comum para nomes próprios/termos emprestados) loga em `DEBUG`, não `INFO` — não deve poluir o log padrão do workflow |
| `test_contador_de_resultado_identico_nao_precisa_ser_consecutivo` | O contador de tentativas "sem erro e resultado idêntico" soma o total mesmo com uma exceção intercalada, não exige consecutividade |
| `test_log_warning_em_caso_de_excecao` | Mensagem `"Falha ao traduzir"` aparece no log de warning quando a tradução falha |
| `test_contexto_aparece_no_log` | O parâmetro `contexto` aparece na mensagem de log de warning |
| `test_cria_translator_com_idiomas_corretos` | `GoogleTranslator` é instanciado com `source="auto", target="pt"` (detecção automática do idioma de origem) |

## Casos de teste — `test_traducao_aws.py`

### `TestTraduzirTextoAws`

Testa `traduzir_texto_aws` via `boto3.client("translate")` mockado.

| Teste | O que verifica |
|---|---|
| `test_traduz_com_sucesso` | Chama `translate_text(Text=..., SourceLanguageCode="auto", TargetLanguageCode="pt")` e retorna `TranslatedText` |
| `test_retorna_original_em_caso_de_excecao` | Exceção (ex.: `boto3.client` falhando) retorna o texto original, sem propagar |
| `test_retorna_original_quando_resposta_vazia` | `TranslatedText` vazio retorna o texto original |
| `test_usa_region_default_us_east_1` | Sem `region` informado, usa `us-east-1` (default do parâmetro) — AWS Translate não está disponível em `sa-east-1`, região principal do pipeline |

## Casos de teste — `test_traducao.py`

### `TestResolverTraduzirFn`

Resolve `"google"`/`"aws"` para a função de tradução correspondente — a escolha de
serviço por execução usada por `glue_details`/`glue_etl` (default `"aws"`) e pelos
backfills manuais (default `"google"`). `traduzir_google`/`traduzir_aws` são parâmetros
opcionais (default `traduzir_texto`/`traduzir_texto_aws`) para que um chamador que faça
patch da própria referência local (ex.: `patch("src.utils.traduzir_texto", ...)`)
continue funcionando.

| Teste | O que verifica |
|---|---|
| `test_resolve_google` | `provider="google"` devolve `traduzir_texto` (default) |
| `test_resolve_aws` | `provider="aws"` devolve `traduzir_texto_aws` (default) |
| `test_provider_invalido_levanta_value_error` | Qualquer valor fora de `"google"`/`"aws"` levanta `ValueError` |
| `test_usa_referencias_locais_informadas_pelo_chamador` | Passando `traduzir_google`/`traduzir_aws` explícitos, a função devolve exatamente essas referências (não as do módulo) |

### `TestTraduzirEmParalelo`

| Teste | O que verifica |
|---|---|
| `test_traduz_cada_valor_e_preserva_a_ordem` | Aplica `traduzir_fn` a cada valor via `ThreadPoolExecutor`, preservando a ordem de entrada |
| `test_lista_vazia_nao_chama_traduzir_fn` | Lista vazia retorna `[]` sem chamar `traduzir_fn` |
| `test_usa_max_workers_informado` | `max_workers` é repassado ao `ThreadPoolExecutor`, não hardcoded |

### `TestTraduzirColunaPendente`

Orquestra a tradução de uma coluna: um registro é pulado quando a coluna de destino já
está preenchida e diferente da coluna fonte (já traduzido — nativo do TMDB ou run
anterior do backfill), e retentado quando destino ficou igual à fonte (fallback de uma
tradução que falhou — ver `traduzir_texto`). Usada por `glue_details` e
`scripts/backfill_traducao.py` em vez de cada um manter sua própria cópia da orquestração.

| Teste | O que verifica |
|---|---|
| `test_traduz_registros_elegiveis_pendentes` | Traduz todos os registros elegíveis, gravando na coluna de destino |
| `test_cria_coluna_destino_se_nao_existir` | Cria a coluna de destino como `None` quando ainda não existe no DataFrame |
| `test_pula_registro_ja_traduzido_com_sucesso` | Destino preenchido e diferente da fonte: não chama `traduzir_fn` |
| `test_retenta_quando_destino_igual_a_fonte` | Destino igual à fonte (fallback de falha anterior): é retentado |
| `test_nao_elegivel_nao_e_traduzido` | Registros fora da máscara de elegibilidade não são traduzidos |
| `test_mask_vazia_nao_chama_traduzir_fn` | Máscara vazia retorna `0` sem chamar `traduzir_fn` |
| `test_sucesso_nao_conta_quando_traducao_falha_e_mantem_original` | Resultado igual ao original (falha de `traduzir_fn`) não conta como sucesso |
| `test_usa_max_workers_informado` | `max_workers` é repassado a `traduzir_em_paralelo`, não hardcoded |

### `TestReaproveitarTraducaoExistente`

Pré-preenche a coluna de destino com a tradução já persistida (`df_anterior`) quando a
coluna fonte não mudou para o mesmo `coluna_chave` (default `"id"`) — evita retraduzir
texto idêntico ao da última execução. Não sobrescreve valor já preenchido no `df` novo
(preserva prioridade da tradução nativa do TMDB). Usada por `glue_details`
(`coluna_chave="id"`) e `glue_etl` (`coluna_chave="iso_3166_1"`/`"iso_639_1"`, tabela
`configuration`).

| Teste | O que verifica |
|---|---|
| `test_reaproveita_quando_fonte_identica` | Reaproveita a coluna de destino de `df_anterior` quando a fonte é idêntica para a mesma chave |
| `test_nao_reaproveita_quando_fonte_mudou` | Não reaproveita quando a fonte mudou em relação a `df_anterior` |
| `test_nao_reaproveita_id_novo_sem_historico` | Não reaproveita quando a chave não existe em `df_anterior` |
| `test_df_anterior_none_nao_quebra` | `df_anterior=None` não lança exceção e não altera `df` |
| `test_df_anterior_vazio_nao_quebra` | `df_anterior` vazio não lança exceção e não altera `df` |
| `test_nao_sobrescreve_destino_ja_preenchido` | Não sobrescreve a coluna de destino já preenchida no `df` novo |
| `test_ignora_schema_antigo_sem_coluna` | `df_anterior` sem a coluna de destino (schema antigo) não lança exceção e não reaproveita |
| `test_ids_duplicados_no_df_anterior_usa_ultimo` | Com chaves duplicadas em `df_anterior`, usa o último valor |
| `test_coluna_chave_customizada` | Funciona com `coluna_chave="iso_3166_1"` (caso de uso do `glue_etl`) |
| `test_coluna_chave_customizada_nao_reaproveita_quando_ausente_no_anterior` | Chave customizada ausente em `df_anterior` não reaproveita |

### `TestElegivelOverviewPt` / `TestElegivelTaglinePt` / `TestElegivelKeywordsPt`

As três máscaras (candidatos à tradução de `overview_pt`, `tagline_pt` e `keywords_pt`)
compartilham a mesma regra: elegível quando `original_language != "pt"` e o campo de
origem está preenchido. `overview_pt` ainda depende de `overview_en` estar preenchido
(campos vazios não são reenviados ao tradutor).

| Teste | O que verifica |
|---|---|
| `test_elegivel_quando_en_e_overview_preenchido` (`TestElegivelOverviewPt`) | Idioma `en` com `overview_en` preenchido é elegível |
| `test_elegivel_para_qualquer_idioma_diferente_de_pt` (nas três classes) | Idiomas como `fr`, `ja`, `es` são elegíveis — não é mais uma lista restrita a `en` |
| `test_nao_elegivel_quando_idioma_e_pt` (nas três classes) | `original_language == "pt"` nunca é elegível, mesmo com o campo preenchido — evita reenviar ao Google Translate texto que já está em português |
| `test_nao_elegivel_quando_overview_en_vazio_ou_nulo` (`TestElegivelOverviewPt`) | `overview_en` vazio/`None` não é elegível mesmo com idioma diferente de `pt` |
| `test_nao_elegivel_quando_tagline_vazia_ou_nula` (`TestElegivelTaglinePt`) | `tagline` vazia/`None` não é elegível |
| `test_nao_elegivel_quando_keywords_vazias_ou_nulas` (`TestElegivelKeywordsPt`) | `keywords` vazia/`None` não é elegível |

## Como executar

```bash
# Apenas os testes do shared_src
pytest test/shared_src/ -v

# Com cobertura
pytest test/shared_src/ --cov=app/shared_src --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).
