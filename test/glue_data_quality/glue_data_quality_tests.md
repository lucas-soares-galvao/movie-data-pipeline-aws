# Testes — glue_data_quality

## O que é testado

Testa a função `main()` em `app/glue_data_quality/main.py`, as funções utilitárias em `app/glue_data_quality/src/utils.py` e os rulesets DQDL em `app/glue_data_quality/src/rulesets_dq.py`. Verifica que as regras de qualidade corretas são selecionadas por tabela, que resultados são gravados na camada DQ e que notificações SNS são enviadas quando há falhas.

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

| Teste | O que verifica |
|---|---|
| `test_reads_correct_ruleset_for_discover` | Ruleset correto para `tb_discover_movie_tmdb` é selecionado |
| `test_reads_table_with_year_filter_for_discover` | Leitura do Catalog usa filtro de partição por `year` para tabelas discover |
| `test_reads_table_without_year_filter_for_genre` | Leitura sem filtro de `year` para tabelas estáticas |
| `test_writes_results_to_dq_bucket` | Resultados são gravados no bucket DQ com partição por `source_table` e `year` |
| `test_sends_sns_notification_on_failure` | SNS é acionado quando pelo menos uma regra retorna `Fail` |
| `test_does_not_send_notification_on_all_pass` | SNS **não** é acionado quando todas as regras passam |

## Casos de teste — `test_utils.py`

| Teste | O que verifica |
|---|---|
| `test_get_ruleset_returns_string` | `get_ruleset` retorna string DQDL para tabelas conhecidas |
| `test_get_ruleset_raises_for_unknown_table` | `get_ruleset` levanta erro para tabela sem ruleset configurado |
| `test_partitions_by_source_table_and_year_when_year_provided` | Tabelas com partição por ano: `partition_cols=["source_table", "year"]` preserva histórico |
| `test_partitions_by_source_table_only_when_no_year` | Tabelas sem partição: `partition_cols=["source_table"]` e coluna `year` é removida |
| `test_notify_failed_only_filters_fail_rows` | Apenas linhas com `Outcome="Fail"` são incluídas na notificação |
| `test_notify_formats_message_correctly` | Mensagem SNS contém nome da tabela e regras que falharam |

## Casos de teste — `test_rulesets_dq.py`

Verifica que cada tabela do projeto tem um ruleset DQDL configurado em `rulesets_dq.py`:

| Teste | O que verifica |
|---|---|
| `test_all_discover_tables_have_ruleset` | `tb_discover_movie_tmdb` e `tb_discover_tv_tmdb` têm regras |
| `test_all_genre_tables_have_ruleset` | Tabelas de gênero têm regras de completude e unicidade |
| `test_all_details_tables_have_ruleset` | Tabelas de detalhes têm regras de completude |
| `test_all_watch_providers_tables_have_ruleset` | Tabelas de watch providers têm regras configuradas |
| `test_ruleset_is_valid_dqdl_string` | Cada ruleset começa com `Rules = [` (formato DQDL válido) |

## Como executar

```bash
# Apenas os testes do glue_data_quality
pytest test/glue_data_quality/ -v

# Com cobertura
pytest test/glue_data_quality/ --cov=app/glue_data_quality --cov-report=term-missing
```

## Cobertura mínima

**70%** — definido em `pytest.ini` na raiz do projeto.
