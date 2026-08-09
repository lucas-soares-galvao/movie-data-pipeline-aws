# Testes — scripts (backfill)

## O que é testado

Testa os 8 scripts de backfill manual em `scripts/` (`backfill_discover.py`, `backfill_referencias.py`, `backfill_enriquecimento.py`, `backfill_data_quality.py`, `backfill_traducao.py`, `backfill_rename_colunas.py`, `backfill_changes.py`, `backfill_historico.py`) + o módulo compartilhado `backfill_shared.py`, acionados pelo workflow `5. Backfill` (`.github/workflows/05_backfill.yml`). Testes unitários com **pytest**, dependências externas (`boto3`, `awswrangler`, `GoogleTranslator`, AWS Translate, `langdetect`, AWS Comprehend) substituídas por mocks via `unittest.mock` — nenhuma chamada real à AWS, ao Google Translate, ao AWS Translate ou aos detectores de idioma.

O foco principal é o **contrato dos argumentos** enviados a cada serviço (Glue) ou às funções internas replicadas no processo (coleta TMDB, transformação equivalente ao Glue ETL/Details), não cobertura exaustiva de cada branch — esses scripts são runbooks de operação manual, não código do pipeline deployado, e por isso ficam fora do gate de cobertura de 95% (`pytest --cov=app`, que mede só `app/`). Ainda assim, os testes rodam e bloqueiam o CI como qualquer outro teste da suíte (ver "Como executar").

Dois bugs reais motivaram este módulo, ambos numa época em que `backfill_discover.py` e `backfill_referencias.py` ainda montavam um payload de Lambda (nenhum dos dois invoca mais a Lambda API hoje, ver seções próprias abaixo): `backfill_discover.py` enviava a chave `only_discover` e `backfill_referencias.py` enviava `skip_discover` — nenhuma das duas era lida por `app/lambda_api/main.py` (que só reconhecia `only_annual_tables` e `skip_weekly`, este último removido do handler junto com o payload de `backfill_referencias.py`). Como uma chave de dict inexistente não gera erro, o bug só apareceria revisando logs de uma execução real de horas contra prod.

Um terceiro bug real motivou a suíte de checkpoint/retomada: `backfill_enriquecimento.py::_start_glue_job` chamava `client.start_job_run(...)` sem o wrapper de log/re-raise de token expirado que o resto do script já tinha — foi exatamente esse ponto que derrubou um backfill de produção sem deixar rastro do progresso já feito. `test_expired_token_no_start_job_run_loga_e_repropaga` trava essa regressão.

Um quarto bug real motivou a cobertura dos dois códigos de erro: `backfill_shared.is_expired_token_error()` (usado por todos os pontos acima) só reconhecia `ExpiredTokenException` (código do STS). A chamada que efetivamente derrubou um backfill de tradução em produção foi `wr.s3.read_parquet` → `ListObjectsV2`, que retorna o código `ExpiredToken` do S3 — string diferente, então a checagem `==` não batia e o retry automático nunca disparava. Os testes de token expirado em todo `test/scripts/` agora são parametrizados sobre os dois códigos (`ExpiredTokenException` e `ExpiredToken`) para travar essa regressão.

## Estrutura

```
test/scripts/
├── __init__.py
├── conftest.py                        # scripts/ já está no pythonpath (pytest.ini); sem fixtures adicionais
├── requirements_tests.txt             # boto3, awswrangler, pandas, deep_translator
├── test_backfill_discover.py
├── test_backfill_referencias.py
├── test_backfill_enriquecimento.py
├── test_backfill_data_quality.py
├── test_backfill_traducao.py
├── test_backfill_rename_colunas.py
├── test_backfill_changes.py
├── test_backfill_historico.py
└── test_backfill_shared.py
```

Import direto por nome de módulo (`import backfill_discover`), sem pacote — `scripts` foi adicionado a `pythonpath` em `pytest.ini`.

## Casos de teste — `test_backfill_discover.py`

Mesmo estilo de `test_backfill_enriquecimento.py`: `backfill_discover.py` roda a coleta TMDB
(`collect_discover_data`, de `app/lambda_api/src/utils.py`) e a transformação equivalente ao
Glue ETL (`read_from_sor`/`write_parquet_to_sot`, de `app/glue_etl/src/utils.py`) diretamente no
processo, sem invocar Lambda nem acionar o job Glue ETL — os testes mockam essas funções
(`collect_discover_data`, `read_from_sor`, `write_parquet_to_sot`, `get_api_secret`,
`trigger_glue_job`), não mais um cliente `boto3` de Lambda.

### `TestLoopPrincipal`

| Teste | O que verifica |
|---|---|
| `test_total_de_unidades_e_anos_vezes_dois_tipos` | Total de chamadas a `collect_discover_data` = anos × 2 |
| `test_intercala_movie_e_tv_por_ano` | Ordem de tipos alterna `["movie", "tv", "movie", "tv", ...]` dentro de cada ano |
| `test_falha_em_uma_unidade_nao_interrompe_o_backfill` | Soft-fail-continue: uma exceção numa unidade é logada mas não aborta o loop |
| `test_read_e_write_pulados_quando_a_coleta_falha` | `read_from_sor`/`write_parquet_to_sot` não são chamados para a unidade cuja coleta falhou (mesmo bloco `try`) |
| `test_nao_pausa_apos_ultima_unidade` | `time.sleep` não é chamado após a última unidade, mas é chamado no disparo final de DQ (uma vez por tabela) |
| `test_loga_resumo_das_falhas_ao_final` / `test_nao_loga_resumo_quando_tudo_sucede` | Resumo de falhas só aparece no log quando alguma unidade falhou |
| `test_busca_api_key_uma_unica_vez_fora_do_loop` | `get_api_secret` chamado uma única vez, antes do loop |
| `test_api_key_repassada_para_cada_unidade` | `api_key` resolvida uma vez é repassada a cada chamada de `collect_discover_data` |

### `TestPipelineDiscover`

| Teste | O que verifica |
|---|---|
| `test_collect_discover_data_recebe_folder_e_bucket_corretos` | `bucket`/`folder`/`year` batem com `S3_BUCKET_SOR`/`tmdb/discover/{media_type}` |
| `test_read_from_sor_recebe_table_type_discover` | Terceiro argumento posicional de `read_from_sor` é `"discover"` |
| `test_write_parquet_particiona_por_ano_com_overwrite_partitions` | `partition_cols=["year"]`, `mode="overwrite_partitions"` — mesma config de `app/glue_etl/main.py:_TABLE_CONFIG["discover"]` |
| `test_write_parquet_usa_tabela_e_database_do_media_type` | `table_name`/`database` batem com `TABLE_DISCOVER_MOVIE`/`GLUE_DATABASE_MOVIE` (e o par tv) |

### `TestTranslateProviderGuard`

`TRANSLATE_PROVIDER` aqui não traduz nada — só escolhe o serviço primário do detector de idioma
do overview via `resolve_detect_language_fn` (mockado nestes testes), com a mesma proteção de
custo por intervalo de anos de `backfill_enriquecimento.py`/`backfill_traducao.py` (ver
`backfill_shared.apply_translate_cost_guard`).

| Teste | O que verifica |
|---|---|
| `test_translate_provider_default_google_propagado` | `resolve_detect_language_fn` recebe `provider="google"` por padrão |
| `test_translate_provider_aws_propagado_para_intervalo_de_1_ano` | `TRANSLATE_PROVIDER=aws` com `start_year == end_year` chega como `"aws"` |
| `test_translate_provider_aws_rebaixado_para_google_em_intervalo_maior_que_1_ano` | `TRANSLATE_PROVIDER=aws` com `end_year > start_year` é rebaixado para `"google"` |

### `TestErros`

| Teste | O que verifica |
|---|---|
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |
| `test_expired_token_gera_codigo_75` (parametrizado) / `test_outro_erro_nao_gera_codigo_de_retomada` | `expired_token_exit_code` distingue token expirado (retomável) de outros erros |
| `test_token_expirado_em_uma_unidade_propaga_sem_ser_capturado_como_falha_soft` (parametrizado) | Token expirado numa unidade propaga (para `run_with_retry_exit` tratar como exit 75), não vira falha soft-fail-continue |

### `TestCheckpoint`

| Teste | O que verifica |
|---|---|
| `test_pula_unidades_ja_concluidas` | Unidades presentes no checkpoint não geram nova chamada a `collect_discover_data` |
| `test_salva_checkpoint_apenas_para_unidades_com_sucesso` | `put_object` só reflete unidades concluídas com sucesso |
| `test_limpa_checkpoint_ao_concluir_tudo_com_sucesso` / `test_nao_limpa_checkpoint_quando_ha_falhas` | `delete_object` só é chamado quando não sobra nenhuma falha; `main()` retorna `True`/`False` de acordo (consumido por `backfill_historico.py`) |

### `TestDataQualityFinal`

| Teste | O que verifica |
|---|---|
| `test_dispara_dq_uma_vez_por_tabela_cobrindo_o_range_completo` | 2 disparos (`TABLE_DISCOVER_MOVIE`, `TABLE_DISCOVER_TV`) com `YEAR` cobrindo todo o range, não por unidade |
| `test_nao_dispara_dq_quando_ha_falhas` | Nenhum disparo de DQ quando sobra alguma unidade com falha |

### `TestGlueAgg`

`shared.trigger_agg_locally` mockado (ver `test_backfill_shared.py::TestTriggerAggLocally` para o
teste da função em si).

| Teste | O que verifica |
|---|---|
| `test_chamado_uma_vez_quando_sem_falhas` | `trigger_agg_locally` chamado uma vez, com os argumentos corretos (env vars `S3_BUCKET_SPEC`/`S3_PREFIX_SPEC`/`DB_UNIFIED`/`TABLE_DISCOVER_UNIFIED`/`ENVIRONMENT`) |
| `test_nao_chamado_quando_ha_falhas` | Não chamado quando sobra alguma unidade com falha (mesma condição do DQ) |
| `test_nao_chamado_quando_trigger_agg_false` | `main(trigger_agg=False)` suprime a chamada — usado por `backfill_historico.py` |
| `test_chamado_antes_de_clear_checkpoint` | Ordem: `trigger_agg_locally` roda antes de `clear_checkpoint` (evita reprocessar tudo numa retomada por token expirado só para retentar o AGG) |

## Casos de teste — `test_backfill_referencias.py`

Mesmo estilo de `test_backfill_discover.py`/`test_backfill_changes.py`: desde que
`backfill_referencias.py` passou a rodar a coleta TMDB e a transformação
(equivalente ao Glue ETL, via `read_from_sor`/`write_parquet_to_sot` de
`app/glue_etl/src/utils.py`) diretamente no processo, sem payload de Lambda,
os testes mockam as funções chamadas (`collect_genre_data`,
`collect_configuration_data`, `collect_watch_providers_ref`,
`read_from_sor`, `write_parquet_to_sot`, `trigger_glue_job`,
`get_api_secret`), não mais um cliente `boto3` de Lambda.

| Teste | O que verifica |
|---|---|
| `test_coleta_genre_configuration_watch_providers_para_movie_e_tv` | As 3 coletas TMDB rodam para `movie` e `tv`, nessa ordem |
| `test_busca_api_key_uma_unica_vez_fora_do_loop` | `get_api_secret` chamado exatamente uma vez |
| `test_api_key_repassada_para_cada_coleta` | A chave buscada é repassada às 3 funções de coleta |
| `test_grava_as_6_tabelas` | `write_parquet_to_sot` grava as 6 tabelas de referência (genre/configuration/watch_providers_ref × movie/tv) |
| `test_database_correto_por_content_type` | `movie` grava em `GLUE_DATABASE_MOVIE`, `tv` em `GLUE_DATABASE_TV` |
| `test_nenhuma_tabela_e_particionada` | Todas as 6 escritas usam `partition_cols=None`, `mode="overwrite"` |
| `test_read_from_sor_recebe_table_type_correto_por_tabela` | `read_from_sor` é chamado com `(media_type, table_type)` correspondente para as 6 combinações |
| `test_dispara_dq_uma_vez_por_tabela_gravada` | `trigger_glue_job` (Data Quality) é chamado 6 vezes, uma por tabela |
| `test_erro_em_genre_aborta_o_backfill` | Exceção em `collect_genre_data` propaga e impede `collect_configuration_data` de rodar (mesmo formato de "abortar no primeiro erro" de antes, agora por propagação direta, sem `invoke_lambda_sync`) |
| `test_http_error_em_watch_providers_ref_nao_aborta_mas_pula_a_escrita` | `HTTPError` em `collect_watch_providers_ref` é capturado — não aborta o script, mas a tabela correspondente não é escrita nem validada |
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` / `test_outro_erro_nao_gera_codigo_de_retomada` / `test_expired_token_gera_codigo_75` (parametrizado) | Mesmos contratos de erro/retomada dos demais scripts sem checkpoint (`backfill_changes.py`) |

### `TestGlueAgg`

| Teste | O que verifica |
|---|---|
| `test_chamado_uma_vez_ao_final` | `trigger_agg_locally` chamado uma vez ao final de `main()`, com os argumentos corretos — este script não tem `failures`/checkpoint; "sem falhas" = chegou ao fim sem exceção |

## Casos de teste — `test_backfill_enriquecimento.py`

### `TestStartGlueJob`

| Teste | O que verifica |
|---|---|
| `test_argumentos_padrao_sem_force_refetch` / `test_inclui_force_refetch_quando_true` | `_start_glue_job` monta `Arguments` corretos, com `--FORCE_REFETCH` apenas quando `force_refetch=True` |
| `test_expired_token_no_start_job_run_loga_e_repropaga` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) | Regressão: `_start_glue_job` também loga/repropaga erro de token expirado (faltava, era o ponto que derrubou produção) |
| `test_outro_client_error_no_start_job_run_repropaga_sem_log_de_credenciais` | Outro `ClientError` não gera o log específico de credenciais |
| `test_translate_provider_default_google` / `test_translate_provider_aws_explicito` | `--TRANSLATE_PROVIDER` incluído em `Arguments` — default `"google"` (volume alto do re-enriquecimento histórico), sobrescrevível para `"aws"` |

### `TestWaitForJob`

| Teste | O que verifica |
|---|---|
| `test_retorna_imediatamente_quando_ja_terminou` / `test_faz_polling_ate_estado_terminal` | `_wait_for_job` faz polling com `time.sleep(poll_interval)` até estado terminal |
| `test_propaga_expired_token_com_log_claro` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) | Token expirado no polling loga aviso de credenciais e repropaga |
| `test_propaga_outros_client_error_sem_log_de_credenciais` | Outro `ClientError` no polling não gera o log específico de credenciais |

### `TestLoopPrincipal`

| Teste | O que verifica |
|---|---|
| `test_total_de_runs_e_anos_vezes_dois_tipos` | Total de runs = anos × 2 |
| `test_intercala_movie_e_tv_por_ano` | Ordem alterna `movie`/`tv` dentro de cada ano (`movie:2020, tv:2020, movie:2021, tv:2021...`), igual a `backfill_discover.py` |
| `test_falha_em_um_run_nao_interrompe_o_backfill` | Um estado `FAILED` é logado mas **não** aborta o loop (diferente de `backfill_discover.py`, que aborta no primeiro erro) |
| `test_nao_pausa_apos_ultimo_run` | Sem `time.sleep` após o último run |
| `test_loga_resumo_das_falhas_ao_final` | Ao final, loga um resumo único com todas as unidades (`media_type`/`year`/`state`) que falharam |
| `test_nao_loga_resumo_quando_tudo_sucede` | Nenhum log de resumo de falhas quando todos os runs sucedem |
| `test_translate_provider_default_google_propagado_ao_glue` / `test_translate_provider_aws_propagado_ao_glue` | `TRANSLATE_PROVIDER` do ambiente chega em `--TRANSLATE_PROVIDER` de cada `start_job_run` (intervalo de 1 ano) |
| `test_translate_provider_aws_rebaixado_para_google_em_intervalo_maior_que_1_ano` | `TRANSLATE_PROVIDER=aws` com intervalo maior que 1 ano é rebaixado para `"google"` antes de chegar ao Glue (`backfill_shared.apply_translate_cost_guard`) |

### `TestForceRefetch`

| Teste | O que verifica |
|---|---|
| `test_default_e_true` / `test_false_omite_o_argumento` | `FORCE_REFETCH` lido corretamente do ambiente |

### `TestErros`

| Teste | O que verifica |
|---|---|
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |
| `test_expired_token_gera_codigo_75` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) / `test_outro_erro_nao_gera_codigo_de_retomada` | `expired_token_exit_code` distingue token expirado de outros erros |

### `TestCheckpoint`

| Teste | O que verifica |
|---|---|
| `test_pula_unidades_ja_concluidas` | Unidades presentes no checkpoint não geram novo `start_job_run` |
| `test_salva_checkpoint_apenas_para_runs_com_sucesso` | Um run `FAILED` não entra no `completed` — continua pendente para a próxima retomada |
| `test_limpa_checkpoint_ao_concluir_tudo_com_sucesso` | `delete_object` chamado só quando não há falhas; `main()` retorna `True` |
| `test_nao_limpa_checkpoint_quando_ha_falhas` | Com alguma falha "soft", o checkpoint permanece (não chama `delete_object`); `main()` retorna `False` (consumido por `backfill_historico.py`) |

### `TestGlueAgg`

Mesmo padrão de `test_backfill_discover.py::TestGlueAgg` (`trigger_agg_locally` mockado, condicionado
a `not failures` e a `trigger_agg=True`, chamado antes de `clear_checkpoint`).

| Teste | O que verifica |
|---|---|
| `test_chamado_uma_vez_quando_sem_falhas` | `trigger_agg_locally` chamado uma vez, com os argumentos corretos |
| `test_nao_chamado_quando_ha_falhas` | Não chamado quando sobra alguma unidade com falha |
| `test_nao_chamado_quando_trigger_agg_false` | `main(trigger_agg=False)` suprime a chamada — usado por `backfill_historico.py` |
| `test_chamado_antes_de_clear_checkpoint` | Ordem: `trigger_agg_locally` roda antes de `clear_checkpoint` |

## Casos de teste — `test_backfill_data_quality.py`

### `TestTriggerDqJob`

| Teste | O que verifica |
|---|---|
| `test_argumentos_enviados_ao_glue` | `_trigger_dq_job` monta `Arguments` (`--TABLE_NAME`, `--DATABASE`, `--YEAR`) corretos |
| `test_expired_token_loga_e_repropaga` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) | Token expirado no disparo do job loga aviso de credenciais e repropaga |

### `TestLoopPrincipal`

| Teste | O que verifica |
|---|---|
| `test_total_de_execucoes_e_anos_vezes_seis_tabelas` | Total = anos × 6 tabelas |
| `test_percorre_as_seis_tabelas_dentro_de_cada_ano` | Ordem fixa das 6 tabelas dentro de cada ano |
| `test_e_assincrono_nunca_espera_o_job_terminar` | `get_job_run` nunca é chamado — contrato fire-and-forget |
| `test_pausa_entre_anos_mas_nao_apos_o_ultimo` / `test_wait_zero_desativa_a_pausa` | `time.sleep` respeita `WAIT_SECONDS` e não pausa após o último ano |

### `TestErros`

| Teste | O que verifica |
|---|---|
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |
| `test_expired_token_gera_codigo_75` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) / `test_outro_erro_nao_gera_codigo_de_retomada` | `expired_token_exit_code` distingue token expirado de outros erros |

### `TestCheckpoint`

| Teste | O que verifica |
|---|---|
| `test_pula_execucoes_ja_concluidas` | Execuções (tabela+ano) já no checkpoint não são re-submetidas |
| `test_salva_checkpoint_apos_cada_submissao` | `put_object` chamado a cada submissão (submissão bem-sucedida já conta como concluída, fire-and-forget) |
| `test_limpa_checkpoint_ao_concluir_tudo_com_sucesso` | `delete_object` chamado ao final |
| `test_nao_pausa_quando_ano_inteiro_ja_esta_no_checkpoint` | Sem `time.sleep` quando nenhuma tabela do ano precisou ser submetida |

Nenhum teste aqui cobre `trigger_agg_locally` — `backfill_data_quality.py` é o único script que não
chama o Glue AGG (não escreve dado novo, só valida).

## Casos de teste — `test_backfill_traducao.py`

Retry/backoff da tradução em si (`translate_text`, 5 tentativas com backoff) é coberto em `test/shared_src/test_traducao_google.py` — o script apenas importa e usa a função do módulo compartilhado, sem lógica própria de retry. O mesmo vale para a escolha de serviço via `TRANSLATE_PROVIDER` (`resolve_translate_fn`, default `"google"`, testado em `test/shared_src/test_traducao.py`) — `_add_translations_*` e `_backfill_year` só recebem e repassam o `translate_fn` já resolvido por `main()`.

Detecção de idioma (`langdetect` com fallback AWS Comprehend — ver
`shared_utils.idioma`) é aplicada, via `shared_utils.traducao.resolve_pt_translation`,
antes de qualquer tradução nas três colunas: grava `<campo>_detected_language_en` a
partir da fonte e `<campo>_detected_language_pt` a partir do resultado final em
`<campo>_pt`. Quando a fonte já é detectada como `"pt"`, copia direto para
`<campo>_pt` sem chamar `translate_text`. A elegibilidade para tradução usa o idioma
detectado do **resultado** (não uma comparação de string com a fonte): fonte
preenchida, `<campo>_detected_language_pt != "pt"` e `<campo>_translation_attempts`
abaixo do teto (protege contra retry infinito de conteúdo genuinamente não
traduzível). A maioria dos testes abaixo fixa `detect_fn` explicitamente (às vezes
como um mapa de texto→idioma) para isolar do comportamento real do `langdetect`
(textos curtos como "Falhou" ou "Ja traduzido antes" podem ser detectados de forma
pouco confiável).

### `TestAdicionarTraducoesPt`

`original_language` não é critério de elegibilidade em nenhuma das três colunas
(ver `shared_utils.traducao.resolve_pt_translation`) — é o idioma de produção
original do título, não o idioma do texto retornado pela API do TMDB.

| Teste | O que verifica |
|---|---|
| `test_todos_overview_en_vazios_nao_chama_traducao` | `_add_translations_pt` não chama `translate_text` quando `overview_en` está vazio/nulo em todos os registros; `overview_detected_language_pt` fica nulo |
| `test_traduz_independente_do_idioma_original` | Traduz todo registro com `overview_en` preenchido, inclusive `original_language == "pt"` |
| `test_nao_conta_como_sucesso_quando_traducao_falha_e_mantem_original` | Contagem de sucesso ignora registros em que `translate_text` devolveu o texto original (fallback de falha); `overview_detected_language_pt` reflete `"pt"`/diferente por registro |
| `test_pula_registros_ja_traduzidos_com_sucesso` | Registro com `overview_pt` já preenchido e cujo idioma detectado já é `"pt"` não é retraduzido; valor existente é preservado |
| `test_retenta_registro_cujo_overview_pt_ficou_igual_ao_original` | `overview_pt == overview_en` (fallback de falha de um run anterior, idioma detectado não é `"pt"`) é tratado como pendente e re-tentado |
| `test_ignora_registros_com_overview_en_vazio` | Registros com `overview_en` vazio/`None` não entram na contagem de elegíveis |
| `test_todos_ja_traduzidos_nao_chama_traducao` | Quando todos os registros já têm `overview_pt` cujo idioma detectado é `"pt"`, `translate_text` não é chamado |
| `test_idioma_detectado_en_calculado_a_partir_da_fonte` | `overview_detected_language_en` chama `detect_fn` com `overview_en` |
| `test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao` | Fonte detectada como `"pt"` é copiada direto para `overview_pt`, sem chamar `translate_text`; `overview_detected_language_pt` fica `"pt"` |
| `test_overview_precisa_traducao_true_quando_traducao_falha` | `overview_needs_translation` é `True` quando a tradução falha (resultado igual ao original) |
| `test_overview_precisa_traducao_false_quando_ja_em_portugues` | `overview_needs_translation` é `False` quando a fonte já é detectada como `"pt"` (cópia direta) |

### `TestAdicionarTraducoesTaglinePt`

| Teste | O que verifica |
|---|---|
| `test_sem_tagline_nao_chama_traducao` | Não traduz quando `tagline` é nula/vazia |
| `test_traduz_independente_do_idioma_original` | Traduz todo registro com `tagline` preenchida, inclusive `original_language == "pt"` |
| `test_pula_registros_ja_traduzidos` | `tagline_pt` já preenchido e cujo idioma detectado já é `"pt"` não é retraduzido |
| `test_retenta_registro_cujo_tagline_pt_ficou_igual_ao_original` | `tagline_pt == tagline` (fallback de falha anterior, idioma detectado não é `"pt"`) é tratado como pendente |
| `test_guard_de_schema_legado_nao_cria_colunas_novas` | Partição sem a coluna `tagline` (schema antigo) não ganha `tagline_detected_language_en`/`_pt`/`tagline_translation_attempts`/`tagline_needs_translation` — mesmo guard já existente (`return df, 0` antecipado) |
| `test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao` | Fonte detectada como `"pt"` é copiada direto para `tagline_pt`, sem chamar `translate_text` |
| `test_tagline_precisa_traducao_true_quando_traducao_falha` | `tagline_needs_translation` é `True` quando a tradução falha |
| `test_tagline_precisa_traducao_false_quando_ja_em_portugues` | `tagline_needs_translation` é `False` quando a fonte já é detectada como `"pt"` (cópia direta) |

### `TestAdicionarTraducoesKeywordsPt`

| Teste | O que verifica |
|---|---|
| `test_sem_keywords_nao_chama_traducao` | Não traduz quando `keywords` é nula/vazia |
| `test_traduz_independente_do_idioma_original` | Traduz todo registro com `keywords` preenchida, inclusive `original_language == "pt"` — TMDB não localiza keywords por idioma |
| `test_pula_registros_ja_traduzidos` | `keywords_pt` já preenchido e cujo idioma detectado já é `"pt"` não é retraduzido |
| `test_guard_de_schema_legado_nao_cria_colunas_novas` | Partição sem a coluna `keywords` não ganha `keywords_detected_language_en`/`_pt`/`keywords_translation_attempts`/`keywords_needs_translation` |
| `test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao` | Fonte detectada como `"pt"` é copiada direto para `keywords_pt`, sem chamar `translate_text` |
| `test_keywords_precisa_traducao_true_quando_traducao_falha` | `keywords_needs_translation` é `True` quando a tradução falha |
| `test_keywords_precisa_traducao_false_quando_ja_em_portugues` | `keywords_needs_translation` é `False` quando a fonte já é detectada como `"pt"` (cópia direta) |

### `TestBackfillYear`

| Teste | O que verifica |
|---|---|
| `test_sem_arquivos_retorna_false_e_nao_escreve` / `test_df_vazio_retorna_false_e_nao_escreve` | `_backfill_year` pula partições ausentes/vazias sem escrever |
| `test_outras_excecoes_sao_repropagadas` | Exceções que não são `NoFilesFound` são relançadas |
| `test_expired_token_na_leitura_loga_e_repropaga` / `test_expired_token_na_escrita_loga_e_repropaga` (parametrizados: `ExpiredTokenException`/`ExpiredToken`) | Erro de token expirado na leitura ou na escrita loga aviso de credenciais e repropaga |
| `test_escreve_com_particao_e_modo_overwrite_partitions` | `wr.s3.to_parquet` chamado com `partition_cols=["year"]` e `mode="overwrite_partitions"` |
| `test_soma_traduzidos_de_overview_tagline_e_keywords` | `traduzidos` retornado por `_backfill_year` soma os três campos (`overview_pt` + `tagline_pt` + `keywords_pt`), não só `overview_pt` |

### `TestMain`

| Teste | O que verifica |
|---|---|
| `test_backfill_year_chamado_para_cada_ano_e_tipo` / `test_alterna_movie_e_tv_por_ano` / `test_nao_pausa_apos_ultima_chamada` | Orquestração de `main()` (via mock de `_backfill_year`) |
| `test_nao_pausa_quando_particao_nao_traduziu_nada` | `translated_count == 0` (partição vazia/já 100% traduzida, sem chamada de API) não paga a pausa de `BACKFILL_WAIT_SECONDS` — evita desperdiçar tempo num backfill de anos antigos ou de range grande |
| `test_pausa_apenas_apos_particoes_que_traduziram_algo` | Mistura de partições com e sem tradução: pausa só depois das que traduziram algo, nunca depois da última |
| `test_loga_total_de_traduzidos_com_sucesso_acumulado` | O log final soma os traduzidos com sucesso de cada partição (`_backfill_year` retorna `(escreveu, traduzidos)`), não a quantidade de partições |
| `test_translate_provider_default_google` | `translate_fn` repassado a `_backfill_year` usa Google como primário (default) |
| `test_translate_provider_aws_explicito_janela_de_1_ano` | `TRANSLATE_PROVIDER=aws` com intervalo de 1 ano: `translate_fn` usa AWS como primário |
| `test_translate_provider_aws_rebaixado_para_google_em_intervalo_maior_que_1_ano` | `TRANSLATE_PROVIDER=aws` com intervalo maior que 1 ano: rebaixado para Google como primário (`backfill_shared.apply_translate_cost_guard`) |
| `test_traduzir_fn_tem_orcamento_independente_por_particao` | `translate_fn` é recriado a cada partição (ano+tipo) — o orçamento de fallback ao AWS Translate de uma partição não é consumido pela anterior |
| `test_translate_provider_invalido_levanta_erro` | `TRANSLATE_PROVIDER` fora de `"google"`/`"aws"` propaga o `ValueError` de `resolve_translate_fn` |

### `TestErros`

| Teste | O que verifica |
|---|---|
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |
| `test_expired_token_gera_codigo_75` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) / `test_outro_erro_nao_gera_codigo_de_retomada` | `expired_token_exit_code` distingue token expirado de outros erros |

### `TestCheckpoint`

| Teste | O que verifica |
|---|---|
| `test_pula_particoes_ja_concluidas` | Partições (ano+tipo) já no checkpoint não chamam `_backfill_year` de novo |
| `test_salva_checkpoint_apos_cada_particao` | `put_object` chamado a cada partição processada |
| `test_marca_completo_mesmo_quando_backfill_year_retorna_false` | Partição sem dados (`_backfill_year` retorna `False`) ainda conta como concluída — não é falha |
| `test_limpa_checkpoint_ao_concluir_tudo_com_sucesso` | `delete_object` chamado ao final |
| `test_checkpoint_reflete_progresso_parcial_quando_interrompido` | Uma exceção no meio do loop deixa o checkpoint só com as partições já concluídas |

### `TestGlueAgg`

| Teste | O que verifica |
|---|---|
| `test_chamado_antes_de_clear_checkpoint` | `trigger_agg_locally` chamado (com `GLUE_DATA_QUALITY_JOB_NAME`, novo para este script) antes de `clear_checkpoint`, com os argumentos corretos |

## Casos de teste — `test_backfill_rename_colunas.py`

Migra `dt_processamento`/`dt_atualizacao` (nomes legados em português) para
`processed_date`/`updated_date` nos parquets de details/watch_providers já
gravados no S3, sem chamar a API do TMDB — ver docstring de
`scripts/backfill_rename_colunas.py` para o motivo de o pipeline normal
(`backfill_enriquecimento.py`) não bastar sozinho para migrar 100% do
histórico (IDs que saíram do discover atual nunca mais entram no delta
reprocessado).

### `TestRenamePartitionColumn`

| Teste | O que verifica |
|---|---|
| `test_sem_arquivos_retorna_false_e_nao_escreve` / `test_df_vazio_retorna_false_e_nao_escreve` | `_rename_partition_column` pula partições ausentes/vazias sem escrever |
| `test_particao_ja_migrada_sem_coluna_antiga_retorna_false_e_nao_escreve` | Guard central: partição sem a coluna antiga no schema físico (já migrada) não é regravada de novo |
| `test_outras_excecoes_sao_repropagadas` | Exceções que não são `NoFilesFound` são relançadas |
| `test_expired_token_na_leitura_loga_e_repropaga` / `test_expired_token_na_escrita_loga_e_repropaga` (parametrizados: `ExpiredTokenException`/`ExpiredToken`) | Erro de token expirado na leitura ou na escrita loga aviso de credenciais e repropaga |
| `test_particao_totalmente_nao_migrada_preenche_coluna_nova_e_descarta_antiga` | Partição nunca tocada pelo pipeline desde o rename (só tem a coluna antiga) — todo registro ganha a coluna nova, coluna antiga é descartada |
| `test_particao_mista_preserva_coluna_nova_e_usa_antiga_so_para_os_nulos` | Caso dos IDs que saíram do discover atual: registros já reprocessados (coluna nova preenchida) não são sobrescritos pelo coalesce; só os ainda nulos usam o valor da coluna antiga |
| `test_escreve_com_particao_e_modo_overwrite_partitions` | `wr.s3.to_parquet` chamado com `partition_cols=["year"]` e `mode="overwrite_partitions"` |

### `TestMain`

| Teste | O que verifica |
|---|---|
| `test_chama_rename_para_cada_tabela_e_ano` | Total de chamadas = anos × 4 tabelas (details movie/tv, watch_providers movie/tv) |
| `test_percorre_as_quatro_tabelas_com_as_colunas_corretas_dentro_de_cada_ano` | Cada tabela é chamada com o par (coluna antiga, coluna nova) correto — `dt_processamento`/`processed_date` para details, `dt_atualizacao`/`updated_date` para watch_providers |
| `test_usa_ano_atual_como_default_de_end_year` | `BACKFILL_END_YEAR` ausente usa o ano atual |
| `test_loga_total_de_particoes_regravadas` | O log final soma quantas partições foram efetivamente regravadas (`_rename_partition_column` retorna `True`), não o total de partições verificadas |

### `TestErros`

| Teste | O que verifica |
|---|---|
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |
| `test_expired_token_gera_codigo_75` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) / `test_outro_erro_nao_gera_codigo_de_retomada` | `expired_token_exit_code` distingue token expirado de outros erros |

### `TestCheckpoint`

| Teste | O que verifica |
|---|---|
| `test_pula_particoes_ja_concluidas` | Partições (`tabela:ano`) já no checkpoint não chamam `_rename_partition_column` de novo |
| `test_salva_checkpoint_apos_cada_particao` | `put_object` chamado a cada uma das 4 tabelas processadas |
| `test_marca_completo_mesmo_quando_rename_retorna_false` | Partição já migrada (`_rename_partition_column` retorna `False`) ainda conta como concluída — não é falha |
| `test_limpa_checkpoint_ao_concluir_tudo_com_sucesso` | `delete_object` chamado ao final |
| `test_checkpoint_reflete_progresso_parcial_quando_interrompido` (parametrizado) | Uma exceção no meio do loop deixa o checkpoint só com as partições já concluídas |

### `TestGlueAgg`

| Teste | O que verifica |
|---|---|
| `test_chamado_antes_de_clear_checkpoint` | `trigger_agg_locally` chamado (com `GLUE_DATA_QUALITY_JOB_NAME`, novo para este script) antes de `clear_checkpoint` — é o gatilho mais importante na prática, já que a query do AGG usa `processed_date`, coluna que só existe depois deste rename |

## Casos de teste — `test_backfill_changes.py`

Dispara sob demanda o mesmo modo `only_changes_tables` que o cron semanal de domingo já aciona automaticamente — sem checkpoint nem parâmetros de data, estruturalmente igual a `test_backfill_referencias.py`. A janela `[domingo passado, sábado de ontem]` é sempre resolvida dentro de `collect_changes_data` (`app/lambda_api`), fora do escopo deste script.

### `TestContratoDoPayload`

| Teste | O que verifica |
|---|---|
| `test_envia_only_changes_tables` | Payload contém `only_changes_tables: True` |
| `test_payload_nao_contem_chaves_de_tabela` | Payload não inclui nenhuma chave `table_*` — o branch `only_changes_tables` de `main.py` sai antes de lê-las |
| `test_payload_nao_contem_datas` | Regressão: o payload nunca inclui `changes_start_date`/`changes_end_date` — este script não escolhe janela |
| `test_database_correto_por_content_type` | `database` do payload usa `GLUE_DATABASE_MOVIE`/`GLUE_DATABASE_TV` conforme o tipo |
| `test_translate_provider_default_google` / `test_translate_provider_repassado_quando_informado` | `translate_provider` no payload |

### `TestInvocacoes`

| Teste | O que verifica |
|---|---|
| `test_invoca_lambda_uma_vez_para_movie_e_uma_para_tv` | 2 invocações, ordem `["movie", "tv"]` |
| `test_pausa_apenas_entre_as_duas_invocacoes` | `time.sleep` chamado uma única vez |

### `TestErros`

| Teste | O que verifica |
|---|---|
| `test_erro_da_lambda_interrompe_o_backfill` | `RuntimeError` (Lambda com erro) propaga e para o script |
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |

> Nota: as seções `TestContratoDoPayload`/`TestInvocacoes` acima descrevem o payload de invocação
> da Lambda API (`only_changes_tables`) de uma versão anterior do script — `backfill_changes.py`
> hoje não invoca mais a Lambda, roda `collect_changes_data`/`process_changed_ids` diretamente no
> processo (ver docstring do script e `TestLoopPrincipal`/`TestDataQualityFinal` no arquivo de
> teste real). Ver `test/scripts/test_backfill_changes.py` como fonte de verdade até esta seção
> ser reescrita.

### `TestGlueAgg` (`test_backfill_changes.py`)

| Teste | O que verifica |
|---|---|
| `test_chamado_uma_vez_quando_sem_falhas` | `trigger_agg_locally` chamado uma vez ao final, com os argumentos corretos |
| `test_nao_chamado_quando_ha_falhas` | Não chamado quando algum `content_type` falha (`if failures: return` já teria saído antes) |

## Casos de teste — `test_backfill_historico.py`

`backfill_historico.py` encadeia `backfill_discover.py` e `backfill_enriquecimento.py`, chamando o
`main()` de cada um diretamente no processo. Os testes mockam os dois módulos inteiros
(`backfill_historico.backfill_discover`/`backfill_historico.backfill_enriquecimento`) — a lógica
interna de cada um já é coberta em `test_backfill_discover.py`/`test_backfill_enriquecimento.py`;
aqui o foco é só a orquestração entre os dois: ordem, `TABLE_GROUP` definido antes de cada chamada,
interrupção quando um estágio retorna `False`, e o checkpoint de estágio próprio (unidade = nome
do estágio, não `tipo:ano`).

### `TestOrdemDosEstagios`

| Teste | O que verifica |
|---|---|
| `test_roda_discover_e_depois_enriquecimento` | Os dois `main()` são chamados, cada um exatamente uma vez |
| `test_define_table_group_de_cada_estagio_antes_de_chamar` | `TABLE_GROUP` é `"discover"` no momento da primeira chamada e `"detalhes_e_providers"` na segunda |

### `TestInterrupcaoPorFalha`

| Teste | O que verifica |
|---|---|
| `test_nao_chama_enriquecimento_quando_discover_retorna_false` | `backfill_enriquecimento.main()` não é chamado se `backfill_discover.main()` retornar `False` |
| `test_nao_salva_estagio_discover_no_checkpoint_quando_retorna_false` | Nenhum `put_object` no checkpoint de estágio quando `discover` falha |
| `test_salva_discover_mas_nao_limpa_checkpoint_quando_enriquecimento_retorna_false` | `"discover"` é salvo no checkpoint de estágio, mas `delete_object` não é chamado |

### `TestSucessoCompleto`

| Teste | O que verifica |
|---|---|
| `test_salva_os_dois_estagios_e_limpa_checkpoint_ao_final` | 2 `put_object` (um por estágio) seguidos de `delete_object` |
| `test_loga_conclusao_quando_tudo_sucede` | Log final "sem pendências" aparece quando os dois estágios sucedem |

### `TestCheckpointDeEstagio`

| Teste | O que verifica |
|---|---|
| `test_pula_discover_quando_ja_concluido_no_checkpoint` | Checkpoint de estágio já com `"discover"` pula direto para `backfill_enriquecimento.main()` |
| `test_pula_ambos_quando_checkpoint_ja_tem_os_dois_estagios` | Nenhum `main()` chamado; só `clear_checkpoint` |

### `TestErros`

| Teste | O que verifica |
|---|---|
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |
| `test_expired_token_gera_codigo_75` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) / `test_outro_erro_nao_gera_codigo_de_retomada` | `expired_token_exit_code` distingue token expirado de outros erros |
| `test_token_expirado_no_estagio_discover_propaga_e_nao_chama_enriquecimento` (parametrizado) | Um `ClientError` de token expirado levantado dentro de `backfill_discover.main()` propaga através de `backfill_historico.main()` sem ser capturado como falha soft |

### `TestGlueAgg`

Caso crítico da internalização do AGG: evitar 2 disparos por execução de `historico` (um por
estágio encadeado).

| Teste | O que verifica |
|---|---|
| `test_estagios_chamados_com_trigger_agg_false` | `backfill_discover.main`/`backfill_enriquecimento.main` são chamados com `trigger_agg=False` — suprime o disparo que cada um faria sozinho |
| `test_chamado_exatamente_uma_vez_quando_ambos_estagios_sucedem` | `trigger_agg_locally` chamado exatamente 1 vez, no nível do próprio `historico`, com os argumentos corretos |
| `test_nao_chamado_quando_discover_retorna_false` / `test_nao_chamado_quando_enriquecimento_retorna_false` | Não chamado se qualquer estágio retornar `False` |
| `test_chamado_uma_unica_vez_mesmo_quando_ambos_estagios_ja_estavam_no_checkpoint` | Retomada: os dois estágios são pulados (já concluídos), mas o AGG ainda roda 1 vez (pode não ter sido disparado antes de uma interrupção anterior) |

## Casos de teste — `test_backfill_shared.py`

### Checkpoint (`load_checkpoint`/`save_checkpoint`/`clear_checkpoint`)

| Teste | O que verifica |
|---|---|
| `test_sem_checkpoint_retorna_vazio` | `NoSuchKey` no `get_object` retorna conjunto vazio |
| `test_checkpoint_compativel_retorna_completed` | Checkpoint com o mesmo `start_year`/`end_year` retorna as unidades salvas |
| `test_checkpoint_range_incompativel_retorna_vazio_e_loga_aviso` | Range diferente do salvo é ignorado (loga aviso), não apagado |
| `test_outro_client_error_e_repropagado` | `ClientError` que não é `NoSuchKey`/token expirado propaga |
| `test_expired_token_loga_e_repropaga` (load/save/clear; parametrizado: `ExpiredTokenException`/`ExpiredToken`) | Token expirado loga e repropaga nos 3 pontos de acesso a S3 |
| `test_grava_json_esperado` | `save_checkpoint` grava `start_year`, `end_year`, `completed` (ordenado) e `updated_at` |
| `test_chama_delete_object_com_a_chave_correta` | `clear_checkpoint` remove exatamente `tmdb/backfill_checkpoints/{table_group}.json` |
| `test_codigos_de_token_expirado_retornam_true` / `test_outros_codigos_retornam_false` (parametrizados) | `is_expired_token_error` reconhece `ExpiredTokenException` (STS) e `ExpiredToken` (S3); rejeita outros códigos |
| `test_expired_token_retorna_codigo_retomavel` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) / `test_outro_erro_retorna_none` | `expired_token_exit_code` só retorna `RETRYABLE_EXIT_CODE` (75) para token expirado |

### `TestTriggerAggLocally`

`run_athena_query`/`write_parquet_to_spec`/`trigger_glue_job` mockados na origem
(`app.glue_agg.src.utils.*`, não em `backfill_shared.*` — a função importa esses símbolos
localmente dentro dela mesma, ver docstring de `trigger_agg_locally`). O arquivo de teste importa
`app.glue_agg.src.utils` antecipadamente (com o mesmo `sys.path.insert` de `app/glue_agg` que a
função faz em runtime) porque `test/scripts/` não passa pelo mecanismo de alias de suíte Glue de
`test/conftest.py`.

| Teste | O que verifica |
|---|---|
| `test_caminho_feliz_chama_query_escrita_e_dq_na_ordem_certa` | `run_athena_query` → `write_parquet_to_spec` → `trigger_glue_job`, nessa ordem, com os argumentos corretos (réplica de `app/glue_agg/main.py`) |
| `test_client_error_nao_token_expirado_e_logado_e_nao_propaga` | `ClientError` que não é token expirado é capturado e logado como `ERROR` — não propaga (não deve derrubar um backfill que já terminou) |
| `test_client_error_token_expirado_propaga` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) | Token expirado propaga (recuperável via exit 75) |
| `test_excecao_generica_e_logada_e_nao_propaga` | Qualquer outra exceção (ex.: `RuntimeError` de `write_parquet_to_spec`) também é capturada e logada, sem propagar |

### Helpers comuns (`require_env`, `apply_translate_cost_guard`, `read_year_range`, `run_with_retry_exit`, `log_resume_progress`)

| Teste | O que verifica |
|---|---|
| `TestRequireEnv` | Retorna o valor quando a env var existe; lança `EnvironmentError` quando ausente ou vazia |
| `TestApplyTranslateCostGuard` | Mantém `"aws"` para intervalo de 1 ano; rebaixa para `"google"` quando o intervalo cobre mais de 1 ano; não mexe quando já é `"google"`; loga aviso quando rebaixa |
| `TestReadYearRange` | Usa `2000`/ano atual como default; lê `BACKFILL_START_YEAR`/`BACKFILL_END_YEAR`; aceita nomes de env var customizados |
| `TestRunWithRetryExit` | Sucesso não sai do processo; token expirado sai com `SystemExit(75)`; outro `ClientError` repropaga |
| `TestLogResumeProgress` | Loga a mensagem de progresso quando há unidades já concluídas; não loga nada quando não há progresso salvo |

## Como executar

```bash
# Apenas os testes dos scripts de backfill
pytest test/scripts/ -v
```

## Cobertura

Sem gate de cobertura dedicado — `scripts/` não entra em `--cov=app`. Os testes rodam junto com o resto da suíte (`testpaths = test` em `pytest.ini`) e são **bloqueantes**: uma falha aqui reprova o step "Run tests with Coverage Gate" do CI (`.github/workflows/01_test.yml`) do mesmo jeito que uma falha em `app/`, só não conta para o percentual de cobertura exigido.
