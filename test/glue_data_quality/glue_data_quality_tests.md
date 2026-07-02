# Testes — glue_data_quality

## O que é testado

Testa a função `main()` em `app/glue_data_quality/main.py`, as funções utilitárias em `app/glue_data_quality/src/utils.py` e os rulesets DQDL em `app/glue_data_quality/src/rulesets_dq.py`. Verifica que as regras de qualidade corretas são selecionadas por tabela, que resultados são gravados na camada DQ e que notificações SNS são enviadas quando há falhas. Todas as dependências externas (GlueContext, Spark, SNS, S3) são substituídas por **mocks** — objetos falsos que simulam o comportamento esperado sem acionar recursos reais da AWS, mantendo os testes rápidos e gratuitos.

## Estrutura

```
test/glue_data_quality/
├── conftest.py               # Stubs de módulos AWS Glue/PySpark (sem fixtures)
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes da função main()
├── test_utils.py             # Testes das funções utilitárias
└── test_rulesets_dq.py       # Testes dos rulesets DQDL por tabela
```

## Stubs de módulo (`conftest.py`)

`conftest.py` não define fixtures via `@pytest.fixture` — em vez disso, registra em
`sys.modules` stubs dos pacotes que só existem no runtime AWS Glue (`awsglue`,
`awsgluedq`, `pyspark`), usando o helper `_make_module()`. Cada teste individual mocka
`GlueContext`, `SparkContext`, `boto3` e `awswrangler` diretamente via `unittest.mock.patch`.

| Módulo stubado | Atributos relevantes |
|---|---|
| `awsglue.utils` | `getResolvedOptions=None`, `GlueArgumentError=Exception` |
| `awsglue.context` | `GlueContext=None` |
| `awsglue.dynamicframe` | `DynamicFrame=None` |
| `awsgluedq.transforms` | `EvaluateDataQuality=None` |
| `pyspark.sql.functions` | `col=MagicMock()`, `when=MagicMock()` (chamadas diretamente pelo código, precisam ser `MagicMock`, não `None`) |
| `pyspark.sql.types` | `StringType=MagicMock()` |

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
| `test_calls_get_ruleset_with_table_name_and_environment` | `get_ruleset` é chamado com o `TABLE_NAME` e `ENVIRONMENT` dos args |
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
| `test_calls_write_with_output_table` | `write_results_to_s3` recebe o `OUTPUT_TABLE` dos args |
| `test_calls_write_with_none_year_when_not_in_args` | `year=None` para tabelas sem partição por ano |
| `test_calls_write_with_year_when_in_args` | `year` correto para tabelas discover |
| `test_write_is_called_exactly_once` | `write_results_to_s3` é chamado exatamente uma vez por execução |

## Casos de teste — `test_utils.py`

### `TestGetParametersGlue`

| Teste | O que verifica |
|---|---|
| `test_returns_required_args` | Retorna `TABLE_NAME`, `DATABASE`, `DATABASE_RESULTS`, `S3_BUCKET_DATA_QUALITY`, `ENVIRONMENT`, `SNS_TOPIC_ARN_DQ_METRICS`, `OUTPUT_TABLE` |
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
| `test_strips_environment_suffix_prod` | Remove o sufixo `_prod` do nome da tabela ao buscar a chave lógica no dicionário de rulesets |

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

Verifica a lógica de avaliação Spark (mocka `EvaluateDataQuality.apply`, `DynamicFrame`, funções `col`, `lit`, `current_timestamp`, `when`, `StringType`). Cobre: contexto Glue passado corretamente, DynamicFrame recebido, ruleset, nome e banco da tabela, comportamento com `year=None` vs `year` fornecido, enriquecimento de resultados com colunas `source_table`, `source_database`, `datetime_process` e `year`, e que o DataFrame retornado contém colunas esperadas.

### `TestWriteResultsToS3`

Verifica que `write_results_to_s3` grava os resultados DQ no bucket correto com `mode="overwrite_partitions"` e `partition_cols=["source_table", "year"]`. Cobre: caminho S3 correto, `fillna("sem_ano")` para tabelas sem partição, `year` preservado quando fornecido, registro no Glue Catalog no `DATABASE_RESULTS`.

### `TestNotifyFailedOutcomes`

| Teste | O que verifica |
|---|---|
| `test_does_not_publish_when_all_rules_pass` | SNS não é chamado quando todas as regras passam |
| `test_publishes_when_any_rule_fails` | SNS é chamado quando pelo menos uma regra retorna `Failed` |
| `test_subject_contains_environment_uppercased` | Subject contém o ambiente em maiúsculas (o Subject **não** contém o nome da tabela — apenas `[{ENVIRONMENT}] DQ Métrica Falha`) |
| `test_message_contains_table_name` | `table_name` aparece no corpo da mensagem SNS |
| `test_message_contains_failed_rule` | A regra (`rule`) da linha com `Failed` aparece na mensagem |
| `test_message_contains_failure_reason` | O `failure_reason` da regra que falhou aparece na mensagem |
| `test_publishes_to_correct_topic_arn` | SNS é chamado com o `TopicArn` passado como argumento |
| `test_message_lists_all_failed_rules` | Múltiplas falhas → todas as regras com `Failed` aparecem na mensagem |
| `test_message_contains_partition_when_year_provided` | Mensagem contém a partição `year=<ano>` quando `year` é fornecido |
| `test_message_does_not_contain_partition_when_year_is_none` | Mensagem não menciona partição quando `year` é `None` |

## Casos de teste — `test_rulesets_dq.py`

### `TestRulesetsDq`

Funciona como "contrato de cobertura" do dicionário `rulesets_dq`: garante que toda tabela conhecida tem regras bem-formadas e que nenhuma tabela nova é adicionada ao pipeline sem um ruleset correspondente.

As 14 tabelas verificadas por `EXPECTED_TABLES` são (nomes lógicos, sem prefixo `tb_tmdb_` nem sufixo `_{env}`): `configuration_countries`, `configuration_languages`, `genre_movie`, `genre_tv`, `discover_movie`, `discover_tv`, `details_movie`, `details_tv`, `watch_providers_movie`, `watch_providers_tv`, `watch_providers_ref_movie`, `watch_providers_ref_tv`, `now_playing_movie`, `discover_unified`.

| Teste | O que verifica |
|---|---|
| `test_all_expected_tables_are_present` | Todas as 14 tabelas conhecidas (incluindo `now_playing_movie` e `discover_unified`) estão no dicionário `rulesets_dq` |
| `test_each_table_has_at_least_one_rule` | Nenhuma tabela tem lista de regras vazia |
| `test_all_rules_are_strings` | Toda regra é do tipo `str` (formato DQDL) |
| `test_no_empty_rules` | Nenhuma regra é string vazia ou somente espaços |
| `test_all_tables_have_row_count_rule` | Toda tabela tem pelo menos uma regra com `RowCount` |
| `test_discover_tables_validate_vote_average` | `discover_movie`, `discover_tv` e `discover_unified` têm regra validando `vote_average` |
| `test_tables_with_id_have_completeness_and_uniqueness` | Tabelas que têm coluna `id` (discover, details, genre, now_playing) têm `IsComplete "id"` e `IsUnique "id"` |
| `test_now_playing_validates_theater_dates` | `now_playing_movie` valida completude de `theater_start_date` e `theater_end_date` |
| `test_unified_validates_year_completeness` | `discover_unified` valida `IsComplete "year"` para a coluna de partição |
| `test_configuration_tables_validate_name_pt` | `configuration_countries` e `configuration_languages` validam completude de `name_pt` (tradução pt-BR) |
| `test_watch_providers_ref_validate_canonical_name` | `watch_providers_ref_movie` e `watch_providers_ref_tv` validam completude de `canonical_name` (nome normalizado do provedor) |
| `test_watch_providers_validate_provider_type_enum` | `watch_providers_movie` e `watch_providers_tv` validam que `provider_type` é um dos valores permitidos (`flatrate`, `rent`, `buy`) |
| `test_discover_tables_validate_popularity` | `discover_movie`, `discover_tv` e `discover_unified` validam que `popularity` é não-negativo |

## Como executar

```bash
# Apenas os testes do glue_data_quality
pytest test/glue_data_quality/ -v

# Com cobertura
pytest test/glue_data_quality/ --cov=app/glue_data_quality --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).
