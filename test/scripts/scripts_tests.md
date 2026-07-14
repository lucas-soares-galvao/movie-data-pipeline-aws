# Testes — scripts (backfill)

## O que é testado

Testa os 6 scripts de backfill manual em `scripts/` (`backfill_historico.py`, `backfill_referencias.py`, `backfill_enriquecimento.py`, `backfill_data_quality.py`, `backfill_traducao.py`, `backfill_shared.py`), acionados pelo workflow `5. Backfill` (`.github/workflows/05_backfill.yml`). Testes unitários com **pytest**, dependências externas (`boto3`, `awswrangler`, `GoogleTranslator`, AWS Translate) substituídas por mocks via `unittest.mock` — nenhuma chamada real à AWS, ao Google Translate ou ao AWS Translate.

O foco principal é o **contrato do payload/argumentos** enviado a cada serviço (Lambda ou Glue), não cobertura exaustiva de cada branch — esses scripts são runbooks de operação manual, não código do pipeline deployado, e por isso ficam fora do gate de cobertura de 80% (`pytest --cov=app`, que mede só `app/`). Ainda assim, os testes rodam e bloqueiam o CI como qualquer outro teste da suíte (ver "Como executar").

Dois bugs reais motivaram este módulo: `backfill_historico.py` enviava a chave `only_discover` e `backfill_referencias.py` enviava `skip_discover` — nenhuma das duas é lida por `app/lambda_api/main.py` (que só reconhece `only_annual_tables` e `skip_weekly`). Como uma chave de dict inexistente não gera erro, o bug só apareceria revisando logs de uma execução real de horas contra prod. Os testes de contrato de payload existem para travar exatamente esse tipo de regressão.

Um terceiro bug real motivou a suíte de checkpoint/retomada: `backfill_enriquecimento.py::_start_glue_job` chamava `client.start_job_run(...)` sem o wrapper de log/re-raise de token expirado que o resto do script já tinha — foi exatamente esse ponto que derrubou um backfill de produção sem deixar rastro do progresso já feito. `test_expired_token_no_start_job_run_loga_e_repropaga` trava essa regressão.

Um quarto bug real motivou a cobertura dos dois códigos de erro: `backfill_shared.is_expired_token_error()` (usado por todos os pontos acima) só reconhecia `ExpiredTokenException` (código do STS). A chamada que efetivamente derrubou um backfill de tradução em produção foi `wr.s3.read_parquet` → `ListObjectsV2`, que retorna o código `ExpiredToken` do S3 — string diferente, então a checagem `==` não batia e o retry automático nunca disparava. Os testes de token expirado em todo `test/scripts/` agora são parametrizados sobre os dois códigos (`ExpiredTokenException` e `ExpiredToken`) para travar essa regressão.

## Estrutura

```
test/scripts/
├── __init__.py
├── conftest.py                        # scripts/ já está no pythonpath (pytest.ini); sem fixtures adicionais
├── requirements_tests.txt             # boto3, awswrangler, pandas, deep_translator
├── test_backfill_historico.py
├── test_backfill_referencias.py
├── test_backfill_enriquecimento.py
├── test_backfill_data_quality.py
├── test_backfill_traducao.py
└── test_backfill_shared.py
```

Import direto por nome de módulo (`import backfill_historico`), sem pacote — `scripts` foi adicionado a `pythonpath` em `pytest.ini`.

## Casos de teste — `test_backfill_historico.py`

### `TestContratoDoPayload`

| Teste | O que verifica |
|---|---|
| `test_envia_only_annual_tables` | Payload enviado à Lambda contém `only_annual_tables: True` |
| `test_nao_envia_mais_a_chave_only_discover` | Regressão: `only_discover` não existe mais no payload |
| `test_inclui_tabelas_de_referencia_exigidas_pelo_lambda_handler` | `table_genre_movie`, `table_configuration_languages`, `table_watch_providers_ref_movie` continuam no payload (lambda_handler os lê sem `.get()`) |
| `test_start_year_igual_loop_end_year_uma_particao_por_invocacao` | Cada invocação cobre exatamente um ano |

### `TestLoopDeAnos`

| Teste | O que verifica |
|---|---|
| `test_invoca_lambda_duas_vezes_por_ano_movie_e_tv` | Total de invocações = anos × 2 |
| `test_alterna_movie_e_tv_na_ordem_por_ano` | Ordem de tipos é `["movie", "tv"]` dentro de cada ano |
| `test_usa_ano_atual_como_default_de_end_year` | `BACKFILL_END_YEAR` ausente usa o ano atual (mockado via `datetime`) |

### `TestTranslateProviderGuard`

`build_base_payloads` recebe `start_year`/`end_year` aqui (diferente de
`backfill_referencias.py`, que não depende de ano) — proteção de custo do AWS
Translate por intervalo de anos (ver `backfill_shared.apply_translate_cost_guard`).

| Teste | O que verifica |
|---|---|
| `test_mantem_aws_para_intervalo_de_1_ano` | `TRANSLATE_PROVIDER=aws` com `start_year == end_year` chega como `"aws"` no payload |
| `test_rebaixa_aws_para_google_em_intervalo_maior_que_1_ano` | `TRANSLATE_PROVIDER=aws` com `end_year > start_year` é rebaixado para `"google"` no payload |

### `TestPausaEntreInvocacoes` / `TestErros` / `TestAssertSingleYear`

| Teste | O que verifica |
|---|---|
| `test_nao_pausa_apos_ultima_invocacao` | `time.sleep` não é chamado após a última invocação do loop |
| `test_erro_da_lambda_interrompe_o_backfill` | `RuntimeError` (Lambda com erro) propaga e para o script |
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |
| `test_expired_token_loga_e_repropaga` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) | `shared.invoke_lambda_sync` loga aviso de credenciais e repropaga erro de token expirado |
| `test_expired_token_no_topo_sai_com_codigo_75` (parametrizado) / `test_outro_erro_nao_gera_codigo_de_retomada` | `expired_token_exit_code` distingue token expirado (retomável) de outros erros |
| `test_lanca_erro_quando_anos_diferentes` / `test_nao_lanca_erro_quando_anos_iguais` | `_assert_single_year` valida `start_year == loop_end_year` |

### `TestCheckpoint`

| Teste | O que verifica |
|---|---|
| `test_pula_unidades_ja_concluidas` | Unidades presentes no checkpoint não geram nova invocação da Lambda |
| `test_salva_checkpoint_apos_cada_unidade` | `put_object` chamado a cada unidade concluída |
| `test_limpa_checkpoint_ao_concluir_tudo_com_sucesso` | `delete_object` chamado quando o loop termina sem erro |
| `test_checkpoint_reflete_progresso_parcial_quando_interrompido` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) | Uma exceção no meio do loop ainda deixa o checkpoint com as unidades já concluídas |

## Casos de teste — `test_backfill_referencias.py`

| Teste | O que verifica |
|---|---|
| `test_envia_skip_weekly` | Payload contém `skip_weekly: True` |
| `test_nao_envia_mais_a_chave_skip_discover` | Regressão: `skip_discover` não existe mais no payload |
| `test_usa_ano_atual_em_start_year_e_end_year` | `start_year`/`end_year` usam o ano atual (independe de `BACKFILL_START_YEAR`) |
| `test_invoca_lambda_uma_vez_para_movie_e_uma_para_tv` | 2 invocações, ordem `["movie", "tv"]` |
| `test_pausa_apenas_entre_as_duas_invocacoes` | `time.sleep` chamado uma única vez |
| `test_erro_da_lambda_interrompe_o_backfill` / `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | Mesmos contratos de erro do `backfill_historico.py` |

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
| `test_intercala_movie_e_tv_por_ano` | Ordem alterna `movie`/`tv` dentro de cada ano (`movie:2020, tv:2020, movie:2021, tv:2021...`), igual a `backfill_historico.py` |
| `test_falha_em_um_run_nao_interrompe_o_backfill` | Um estado `FAILED` é logado mas **não** aborta o loop (diferente de `backfill_historico.py`, que aborta no primeiro erro) |
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
| `test_limpa_checkpoint_ao_concluir_tudo_com_sucesso` | `delete_object` chamado só quando não há falhas |
| `test_nao_limpa_checkpoint_quando_ha_falhas` | Com alguma falha "soft", o checkpoint permanece (não chama `delete_object`) |

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

## Casos de teste — `test_backfill_traducao.py`

Retry/backoff da tradução em si (`translate_text`, 5 tentativas com backoff) é coberto em `test/shared_src/test_traducao_google.py` — o script apenas importa e usa a função do módulo compartilhado, sem lógica própria de retry. O mesmo vale para a escolha de serviço via `TRANSLATE_PROVIDER` (`resolve_translate_fn`, default `"google"`, testado em `test/shared_src/test_traducao.py`) — `_adicionar_traducoes_*` e `_backfill_year` só recebem e repassam o `traduzir_fn` já resolvido por `main()`.

### `TestAdicionarTraducoesPt`

| Teste | O que verifica |
|---|---|
| `test_sem_registros_en_nao_chama_traducao` | `_adicionar_traducoes_pt` não chama `translate_text` quando não há registros `en` |
| `test_traduz_apenas_registros_en` | `_adicionar_traducoes_pt` só traduz `original_language == "en"` |
| `test_nao_conta_como_sucesso_quando_traducao_falha_e_mantem_original` | Contagem de sucesso ignora registros em que `translate_text` devolveu o texto original (fallback de falha) |
| `test_pula_registros_ja_traduzidos_com_sucesso` | Registro com `overview_pt` já preenchido e diferente de `overview_en` não é retraduzido; valor existente é preservado |
| `test_retenta_registro_cujo_overview_pt_ficou_igual_ao_original` | `overview_pt == overview_en` (fallback de falha de um run anterior) é tratado como pendente e re-tentado |
| `test_todos_ja_traduzidos_nao_chama_traducao` | Quando todos os registros `en` já têm tradução válida, `translate_text` não é chamado |

### `TestAdicionarTraducoesTaglinePt`

| Teste | O que verifica |
|---|---|
| `test_sem_tagline_nao_chama_traducao` | Não traduz quando `tagline` é nula/vazia |
| `test_traduz_qualquer_idioma_sem_filtro_original_language` | Diferente de `overview_pt`, `tagline_pt` não filtra por `original_language` (espelha `glue_details`) |
| `test_pula_registros_ja_traduzidos` | `tagline_pt` já preenchido e diferente de `tagline` não é retraduzido |
| `test_retenta_registro_cujo_tagline_pt_ficou_igual_ao_original` | `tagline_pt == tagline` (fallback de falha anterior) é tratado como pendente |

### `TestAdicionarTraducoesKeywordsPt`

| Teste | O que verifica |
|---|---|
| `test_sem_keywords_nao_chama_traducao` | Não traduz quando `keywords` é nula/vazia |
| `test_traduz_qualquer_idioma_sem_filtro_original_language` | `keywords_pt` não filtra por `original_language` — TMDB sempre devolve keywords em inglês |
| `test_pula_registros_ja_traduzidos` | `keywords_pt` já preenchido e diferente de `keywords` não é retraduzido |

### `TestLoadDiscoverMap`

| Teste | O que verifica |
|---|---|
| `test_remove_duplicatas_e_seleciona_colunas` | `_load_discover_map` deduplica por `id` e retorna só `id`/`original_language` |
| `test_expired_token_loga_e_repropaga` (parametrizado: `ExpiredTokenException`/`ExpiredToken`) | Erro de token expirado na leitura loga aviso de credenciais e repropaga |

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
| `test_carrega_discover_map_uma_vez_por_tipo` / `test_backfill_year_chamado_para_cada_ano_e_tipo` / `test_alterna_movie_e_tv_por_ano` / `test_nao_pausa_apos_ultima_chamada` | Orquestração de `main()` (via mocks de `_load_discover_map`/`_backfill_year`) |
| `test_loga_total_de_traduzidos_com_sucesso_acumulado` | O log final soma os traduzidos com sucesso de cada partição (`_backfill_year` retorna `(escreveu, traduzidos)`), não a quantidade de partições |
| `test_translate_provider_default_google` | `traduzir_fn` repassado a `_backfill_year` usa Google como primário (default) |
| `test_translate_provider_aws_explicito_janela_de_1_ano` | `TRANSLATE_PROVIDER=aws` com intervalo de 1 ano: `traduzir_fn` usa AWS como primário |
| `test_translate_provider_aws_rebaixado_para_google_em_intervalo_maior_que_1_ano` | `TRANSLATE_PROVIDER=aws` com intervalo maior que 1 ano: rebaixado para Google como primário (`backfill_shared.apply_translate_cost_guard`) |
| `test_traduzir_fn_tem_orcamento_independente_por_particao` | `traduzir_fn` é recriado a cada partição (ano+tipo) — o orçamento de fallback ao AWS Translate de uma partição não é consumido pela anterior |
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

### Helpers comuns (`require_env`, `invoke_lambda_sync`, `build_base_payloads`, `read_year_range`, `run_with_retry_exit`, `log_resume_progress`)

| Teste | O que verifica |
|---|---|
| `TestRequireEnv` | Retorna o valor quando a env var existe; lança `EnvironmentError` quando ausente ou vazia |
| `TestInvokeLambdaSync` | Sucesso não lança erro; `StatusCode != 200` lança `RuntimeError`; token expirado loga e repropaga |
| `TestBuildBasePayloads` | Monta `base_movie`/`base_tv` com os campos esperados; env var ausente lança `EnvironmentError`; `translate_provider` default `"google"` quando `TRANSLATE_PROVIDER` ausente, sobrescrevível via env var (cobre `backfill_historico.py`/`backfill_referencias.py`); sem `start_year`/`end_year` (uso de `backfill_referencias.py`) o guard de custo não se aplica; com `start_year`/`end_year` (uso de `backfill_historico.py`), `apply_translate_cost_guard` é aplicado antes de montar os payloads |
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
