# Testes — lambda_glue_orchestrator

## O que é testado

Testa a função `lambda_handler` em `app/lambda_glue_orchestrator/main.py` e `wait_for_job_runs` em `app/lambda_glue_orchestrator/src/utils.py`. Testes unitários com `pytest` (classes simples, `assert` nativo, `with patch(...)`), todas as chamadas AWS mockadas via `unittest.mock`.

## Estrutura

```
test/lambda_glue_orchestrator/
├── conftest.py               # Placeholder de configuração (sem fixtures no momento)
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes do lambda_handler
└── test_utils.py             # Testes de wait_for_job_runs
```

## Casos de teste — `test_utils.py`

### `TestWaitForJobRuns`

| Teste | O que verifica |
|---|---|
| `test_consulta_get_job_run_para_cada_item_de_wait_for` | `get_job_run` é chamado uma vez por item de `wait_for`, com `JobName`/`RunId` corretos — inclusive com `job_name` diferentes entre itens |
| `test_faz_polling_ate_estado_terminal` | Enquanto o estado é `RUNNING`, `time.sleep` é chamado e `get_job_run` é consultado de novo, até um estado terminal |
| `test_nao_levanta_excecao_quando_job_falha` | Um job em `FAILED` não interrompe a espera pelos demais itens de `wait_for` |
| `test_loga_erro_quando_job_nao_termina_em_succeeded` | Estado terminal diferente de `SUCCEEDED` (ex: `TIMEOUT`) é logado como erro |
| `test_lista_vazia_nao_chama_get_job_run` | `wait_for=[]` não faz nenhuma chamada |

## Casos de teste — `test_main.py`

### `TestLambdaHandler`

| Teste | O que verifica |
|---|---|
| `test_espera_os_jobs_de_wait_for` | `wait_for_job_runs` é chamado com a lista de `event["wait_for"]` |
| `test_usa_cliente_glue` | `boto3.client("glue")` é usado |
| `test_aciona_target_job_name_apos_esperar` | `trigger_glue_job` é chamado com `event["target_job_name"]` |
| `test_repassa_target_job_args_quando_informado` | `target_job_args` (opcional) é repassado como kwargs a `trigger_glue_job` |
| `test_retorna_status_200` | Handler retorna `{"statusCode": 200}` com o nome do job alvo no corpo |
| `test_ordem_espera_antes_de_acionar` | `wait_for_job_runs` é chamado antes de `trigger_glue_job` — a ordem importa, senão o job alvo rodaria antes dos jobs em `wait_for` terminarem |

## Como executar

```bash
# Apenas os testes da lambda_glue_orchestrator
pytest test/lambda_glue_orchestrator/ -v

# Com cobertura
pytest test/lambda_glue_orchestrator/ --cov=app/lambda_glue_orchestrator --cov-report=term-missing
```

## Cobertura mínima

**95%** — definido via `--cov-fail-under=95` no workflow de CI (`.github/workflows/01_test.yml`).
