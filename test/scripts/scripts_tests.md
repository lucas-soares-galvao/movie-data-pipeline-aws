# Testes — scripts (backfill)

## O que é testado

Testa os 5 scripts de backfill manual em `scripts/` (`backfill_historico.py`, `backfill_referencias.py`, `backfill_enriquecimento.py`, `backfill_data_quality.py`, `backfill_traducao.py`), acionados pelo workflow `5. Backfill` (`.github/workflows/05_backfill.yml`). Testes unitários com **pytest**, dependências externas (`boto3`, `awswrangler`, `GoogleTranslator`) substituídas por mocks via `unittest.mock` — nenhuma chamada real à AWS ou ao Google Translate.

O foco principal é o **contrato do payload/argumentos** enviado a cada serviço (Lambda ou Glue), não cobertura exaustiva de cada branch — esses scripts são runbooks de operação manual, não código do pipeline deployado, e por isso ficam fora do gate de cobertura de 80% (`pytest --cov=app`, que mede só `app/`). Ainda assim, os testes rodam e bloqueiam o CI como qualquer outro teste da suíte (ver "Como executar").

Dois bugs reais motivaram este módulo: `backfill_historico.py` enviava a chave `only_discover` e `backfill_referencias.py` enviava `skip_discover` — nenhuma das duas é lida por `app/lambda_api/main.py` (que só reconhece `only_annual_tables` e `skip_weekly`). Como uma chave de dict inexistente não gera erro, o bug só apareceria revisando logs de uma execução real de horas contra prod. Os testes de contrato de payload existem para travar exatamente esse tipo de regressão.

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
└── test_backfill_traducao.py
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

### `TestPausaEntreInvocacoes` / `TestErros` / `TestAssertSingleYear`

| Teste | O que verifica |
|---|---|
| `test_nao_pausa_apos_ultima_invocacao` | `time.sleep` não é chamado após a última invocação do loop |
| `test_erro_da_lambda_interrompe_o_backfill` | `RuntimeError` (Lambda com erro) propaga e para o script |
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |
| `test_lanca_erro_quando_anos_diferentes` / `test_nao_lanca_erro_quando_anos_iguais` | `_assert_single_year` valida `start_year == loop_end_year` |

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

| Teste | O que verifica |
|---|---|
| `test_argumentos_padrao_sem_force_refetch` / `test_inclui_force_refetch_quando_true` | `_start_glue_job` monta `Arguments` corretos, com `--FORCE_REFETCH` apenas quando `force_refetch=True` |
| `test_retorna_imediatamente_quando_ja_terminou` / `test_faz_polling_ate_estado_terminal` | `_wait_for_job` faz polling com `time.sleep(poll_interval)` até estado terminal |
| `test_total_de_runs_e_anos_vezes_dois_tipos` | Total de runs = anos × 2 |
| `test_roda_todos_os_anos_de_movie_antes_de_tv` | Ordem é todos os anos de `movie`, depois todos os anos de `tv` (diferente de `backfill_historico.py`, que alterna por ano) |
| `test_falha_em_um_run_nao_interrompe_o_backfill` | Um estado `FAILED` é logado mas **não** aborta o loop (diferente de `backfill_historico.py`, que aborta no primeiro erro) |
| `test_nao_pausa_apos_ultimo_run` | Sem `time.sleep` após o último run |
| `test_default_e_true` / `test_false_omite_o_argumento` | `FORCE_REFETCH` lido corretamente do ambiente |
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |

## Casos de teste — `test_backfill_data_quality.py`

| Teste | O que verifica |
|---|---|
| `test_argumentos_enviados_ao_glue` | `_trigger_dq_job` monta `Arguments` (`--TABLE_NAME`, `--DATABASE`, `--YEAR`) corretos |
| `test_total_de_execucoes_e_anos_vezes_seis_tabelas` | Total = anos × 6 tabelas |
| `test_percorre_as_seis_tabelas_dentro_de_cada_ano` | Ordem fixa das 6 tabelas dentro de cada ano |
| `test_e_assincrono_nunca_espera_o_job_terminar` | `get_job_run` nunca é chamado — contrato fire-and-forget |
| `test_pausa_entre_anos_mas_nao_apos_o_ultimo` / `test_year_sleep_zero_desativa_a_pausa` | `time.sleep` respeita `YEAR_SLEEP_SECONDS` e não pausa após o último ano |
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |

## Casos de teste — `test_backfill_traducao.py`

| Teste | O que verifica |
|---|---|
| `test_string_vazia_retorna_vazia_sem_chamar_google` | `_translate("")` não chama `GoogleTranslator` |
| `test_traduz_com_sucesso_na_primeira_tentativa` / `test_tenta_novamente_apos_excecao_e_depois_sucede` / `test_retorna_texto_original_apos_tres_falhas` | Retry de `_translate` (até 3 tentativas, fallback para o texto original) |
| `test_sem_registros_en_nao_chama_traducao` / `test_traduz_apenas_registros_en` | `_adicionar_traducoes_pt` só traduz `original_language == "en"` |
| `test_remove_duplicatas_e_seleciona_colunas` | `_load_discover_map` deduplica por `id` e retorna só `id`/`original_language` |
| `test_sem_arquivos_retorna_false_e_nao_escreve` / `test_df_vazio_retorna_false_e_nao_escreve` | `_backfill_year` pula partições ausentes/vazias sem escrever |
| `test_outras_excecoes_sao_repropagadas` | Exceções que não são `NoFilesFound` são relançadas |
| `test_escreve_com_particao_e_modo_overwrite_partitions` | `wr.s3.to_parquet` chamado com `partition_cols=["year"]` e `mode="overwrite_partitions"` |
| `test_carrega_discover_map_uma_vez_por_tipo` / `test_backfill_year_chamado_para_cada_ano_e_tipo` / `test_alterna_movie_e_tv_por_ano` / `test_nao_pausa_apos_ultima_chamada` | Orquestração de `main()` (via mocks de `_load_discover_map`/`_backfill_year`) |
| `test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro` | `EnvironmentError` quando falta variável obrigatória |

## Como executar

```bash
# Apenas os testes dos scripts de backfill
pytest test/scripts/ -v
```

## Cobertura

Sem gate de cobertura dedicado — `scripts/` não entra em `--cov=app`. Os testes rodam junto com o resto da suíte (`testpaths = test` em `pytest.ini`) e são **bloqueantes**: uma falha aqui reprova o step "Run tests with Coverage Gate" do CI (`.github/workflows/01_test.yml`) do mesmo jeito que uma falha em `app/`, só não conta para o percentual de cobertura exigido.
