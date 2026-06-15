# Testes — glue_data_quality

## O que é testado

Testa a função `main()` em `app/glue_data_quality/main.py`, as funções utilitárias em `app/glue_data_quality/src/utils.py` e os rulesets DQDL em `app/glue_data_quality/src/rulesets_dq.py`. Verifica que as regras de qualidade corretas são selecionadas por tabela, que resultados são gravados na camada DQ e que notificações SNS são enviadas quando há falhas. Todas as dependências externas (GlueContext, Spark, SNS, S3) são substituídas por **mocks** — objetos falsos que simulam o comportamento esperado sem acionar recursos reais da AWS, mantendo os testes rápidos e gratuitos.

## Estrutura

```
test/glue_data_quality/
├── conftest.py               # Fixtures locais da suite
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes da função main()
├── test_utils.py             # Testes das funções utilitárias
└── test_rulesets_dq.py       # Testes dos rulesets DQDL por tabela
```

## Fixtures (`conftest.py`)

| Fixture | Tipo | Descrição |
|---|---|---|
| `mock_glue_context` | `MagicMock` | Substitui `GlueContext` e `SparkContext` do ambiente Glue |
| `mock_dynamic_frame` | `MagicMock` | DataFrame Spark simulado para avaliação de regras |
| `mock_dq_results` | `pd.DataFrame` | Resultados simulados da avaliação DQ (Pass/Fail por regra) |
| `mock_boto3_sns` | `MagicMock` | Substitui cliente SNS para verificar envio de notificações |
| `mock_awswrangler` | `MagicMock` | Substitui escrita Parquet no S3 DQ |

## Casos de teste — `test_main.py`

Os testes de `test_main.py` verificam que `main()` coordena corretamente os colaboradores. Todos os colaboradores são mockados via `_run_main()`, um helper que aplica `patch.object` em todos os módulos importados e retorna os mocks para inspeção.

### `TestContextCreation`

| Teste | O que verifica |
|---|---|
| `test_creates_spark_context` | `SparkContext.getOrCreate()` é chamado para iniciar o Spark |
| `test_creates_glue_context_with_spark_context` | `GlueContext` é criado passando o `SparkContext` como argumento |

### `TestGetRulesetCall`

| Teste | O que verifica |
|---|---|
| `test_calls_get_ruleset_with_table_name` | `get_ruleset` é chamado com o `TABLE_NAME` dos args |
| `test_calls_get_ruleset_for_discover_table` | `get_ruleset` funciona para qualquer nome de tabela |

### `TestReadTableFromCatalogCall`

| Teste | O que verifica |
|---|---|
| `test_calls_read_table_with_glue_context` | `read_table_from_catalog` recebe o `GlueContext` criado no `main` |
| `test_calls_read_table_with_database` | `read_table_from_catalog` recebe o `DATABASE` dos args |
| `test_calls_read_table_with_table_name` | `read_table_from_catalog` recebe o `TABLE_NAME` dos args |
| `test_calls_read_table_with_none_year_when_not_in_args` | `year=None` quando `YEAR` não está nos args (tabelas estáticas sem partição) |
| `test_calls_read_table_with_year_when_in_args` | `year` correto quando `YEAR` está nos args (tabelas discover com partição) |

### `TestEvaluateDataQualityCall`

| Teste | O que verifica |
|---|---|
| `test_calls_evaluate_with_glue_context` | `evaluate_data_quality` recebe o `GlueContext` |
| `test_calls_evaluate_with_dynamic_frame_from_catalog` | `evaluate_data_quality` recebe o `DynamicFrame` lido do Catalog |
| `test_calls_evaluate_with_ruleset` | `evaluate_data_quality` recebe o ruleset retornado por `get_ruleset` |
| `test_calls_evaluate_with_table_name` | `evaluate_data_quality` recebe o `TABLE_NAME` dos args |
| `test_calls_evaluate_with_database` | `evaluate_data_quality` recebe o `DATABASE` dos args |
| `test_calls_evaluate_with_none_year_when_not_in_args` | `year=None` quando `YEAR` não está nos args |
| `test_calls_evaluate_with_year_when_in_args` | `year` correto quando `YEAR` está nos args |

### `TestWriteResultsToS3Call`

| Teste | O que verifica |
|---|---|
| `test_calls_write_with_df_results` | `write_results_to_s3` recebe o DataFrame retornado por `evaluate_data_quality` |
| `test_calls_write_with_s3_bucket_data_quality` | `write_results_to_s3` recebe o `S3_BUCKET_DATA_QUALITY` dos args |
| `test_calls_write_with_table_name` | `write_results_to_s3` recebe o `TABLE_NAME` dos args |
| `test_calls_write_with_database` | `write_results_to_s3` recebe `DATABASE_RESULTS` (banco unificado) — **não** o `DATABASE` da tabela avaliada |
| `test_calls_write_with_none_year_when_not_in_args` | `year=None` para tabelas sem partição por ano |
| `test_calls_write_with_year_when_in_args` | `year` correto para tabelas discover |
| `test_write_is_called_exactly_once` | `write_results_to_s3` é chamado exatamente uma vez por execução |

## Casos de teste — `test_utils.py`

### `TestGetParametersGlue`

| Teste | O que verifica |
|---|---|
| `test_returns_required_args` | Retorna `TABLE_NAME`, `DATABASE`, `DATABASE_RESULTS`, `S3_BUCKET_DATA_QUALITY`, `ENVIRONMENT` |
| `test_adds_year_when_available` | `YEAR` é incluído quando o Glue ETL passa o argumento |
| `test_omits_year_when_not_provided` | `YEAR` não está no retorno quando o argumento não é enviado |
| `test_does_not_raise_when_year_is_missing` | Ausência de `YEAR` não lança exceção (argumento opcional) |
| `test_returns_database_results` | `DATABASE_RESULTS` está no retorno como argumento obrigatório |

### `TestGetRuleset`

| Teste | O que verifica |
|---|---|
| `test_starts_with_rules_block` | String retornada começa com `"Rules = ["` (formato DQDL exigido) |
| `test_ends_with_closing_bracket` | String retornada termina com `"]"` |
| `test_contains_all_rules_from_rulesets_dq` | Cada regra definida em `rulesets_dq` aparece na string gerada |
| `test_raises_key_error_for_unknown_table` | Levanta `KeyError` com o nome da tabela para tabelas sem ruleset |
| `test_rules_separated_by_comma` | Quando há mais de uma regra, estão separadas por vírgula |
| `test_works_for_all_tables_in_rulesets_dq` | `get_ruleset` funciona para todas as tabelas cadastradas |

### `TestReadTableFromCatalog`

| Teste | O que verifica |
|---|---|
| `test_calls_from_catalog_with_correct_args` | `from_catalog` chamado com `database` e `table_name` corretos |
| `test_returns_dynamic_frame_from_catalog` | Retorno é exatamente o `DynamicFrame` devolvido pelo Glue |
| `test_uses_provided_database_name` | Nome do banco passado é repassado ao Catalog |
| `test_uses_provided_table_name` | Nome da tabela passado é repassado ao Catalog |
| `test_no_push_down_predicate_when_year_is_none` | Sem `year`, `push_down_predicate` não é passado (tabelas sem partição) |
| `test_push_down_predicate_when_year_is_provided` | Com `year`, `push_down_predicate` filtra apenas a partição informada (`year = '2019'`) |
| `test_push_down_predicate_uses_correct_year_value` | O predicado contém exatamente o ano passado como argumento |

### `TestEvaluateDataQuality`

Verifica a lógica de avaliação Spark (mocka `EvaluateDataQuality.apply`, `DynamicFrame`, funções `col`, `lit`, `current_timestamp`, `when`, `StringType`). Cobre: contexto Glue passado corretamente, DynamicFrame recebido, ruleset, nome e banco da tabela, comportamento com `year=None` vs `year` fornecido, enriquecimento de resultados com colunas `source_table`, `dt_atualizacao` e `year`, e que o DataFrame retornado contém colunas esperadas.

### `TestWriteResultsToS3`

Verifica que `write_results_to_s3` grava os resultados DQ no bucket correto com `mode="overwrite_partitions"` e `partition_cols=["source_table", "year"]`. Cobre: caminho S3 correto, `fillna("sem_ano")` para tabelas sem partição, `year` preservado quando fornecido, registro no Glue Catalog no `DATABASE_RESULTS`.

### `TestNotifyFailedOutcomes`

| Teste (descrição) | O que verifica |
|---|---|
| Sem falhas → não publica | SNS não é chamado quando todas as regras passam |
| Com falha → publica | SNS é chamado quando pelo menos uma regra retorna `Fail` |
| Mensagem contém nome da tabela | `source_table` aparece no corpo da mensagem SNS |
| Mensagem contém regra que falhou | `RuleName` da linha com `Fail` aparece na mensagem |
| Mensagem contém `year` | Partição de ano aparece na mensagem quando fornecida |
| Filtra apenas linhas `Fail` | Linhas com `Outcome="Pass"` não são incluídas na notificação |
| Múltiplas falhas → todas listadas | Todas as regras com `Fail` aparecem na mensagem |
| ARN correto | SNS é chamado com o `TopicArn` passado como argumento |
| Subject correto | Subject da mensagem contém o nome da tabela e o ambiente |
| Retorna `MessageId` | Retorna o `MessageId` da resposta do SNS |

## Casos de teste — `test_rulesets_dq.py`

### `TestRulesetsDq`

Funciona como "contrato de cobertura" do dicionário `rulesets_dq`: garante que toda tabela conhecida tem regras bem-formadas e que nenhuma tabela nova é adicionada ao pipeline sem um ruleset correspondente.

As 14 tabelas verificadas por `EXPECTED_TABLES` são: `tb_configuration_countries_tmdb`, `tb_configuration_languages_tmdb`, `tb_genre_movie_tmdb`, `tb_genre_tv_tmdb`, `tb_discover_movie_tmdb`, `tb_discover_tv_tmdb`, `tb_details_movie_tmdb`, `tb_details_tv_tmdb`, `tb_watch_providers_movie_tmdb`, `tb_watch_providers_tv_tmdb`, `tb_watch_providers_ref_movie_tmdb`, `tb_watch_providers_ref_tv_tmdb`, `tb_now_playing_movie_tmdb`, `tb_discover_unified_tmdb`.

| Teste | O que verifica |
|---|---|
| `test_all_expected_tables_are_present` | Todas as 14 tabelas conhecidas (incluindo `tb_now_playing_movie_tmdb` e `tb_discover_unified_tmdb`) estão no dicionário `rulesets_dq` |
| `test_each_table_has_at_least_one_rule` | Nenhuma tabela tem lista de regras vazia |
| `test_all_rules_are_strings` | Toda regra é do tipo `str` (formato DQDL) |
| `test_no_empty_rules` | Nenhuma regra é string vazia ou somente espaços |
| `test_all_tables_have_row_count_rule` | Toda tabela tem pelo menos uma regra com `RowCount` |
| `test_discover_tables_validate_vote_average` | `tb_discover_movie_tmdb`, `tb_discover_tv_tmdb`, `tb_now_playing_movie_tmdb` e `tb_discover_unified_tmdb` têm regra validando `vote_average` |
| `test_tables_with_id_have_completeness_and_uniqueness` | Tabelas que têm coluna `id` (discover, details, genre, now_playing) têm `IsComplete "id"` e `IsUnique "id"` |

## Como executar

```bash
# Apenas os testes do glue_data_quality
pytest test/glue_data_quality/ -v

# Com cobertura
pytest test/glue_data_quality/ --cov=app/glue_data_quality --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto.
