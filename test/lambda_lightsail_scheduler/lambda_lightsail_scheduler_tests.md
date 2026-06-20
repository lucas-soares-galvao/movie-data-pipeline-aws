# Testes — lambda_lightsail_scheduler

## O que é testado

Testa a função `lambda_handler()` em `app/lambda_lightsail_scheduler/main.py`. Os testes usam estilo **pytest** (classes simples, `assert` nativo, `with patch(...)` como context manager, `pytest.raises()` para exceções). O objetivo é garantir que as ações `start` e `stop` chamam os métodos corretos do boto3 Lightsail com o nome de instância esperado, e que cenários de erro (ação desconhecida, variável de ambiente ausente) levantam as exceções corretas. Todas as chamadas ao boto3 são substituídas por **mocks** via `unittest.mock`.

## Estrutura

```
test/lambda_lightsail_scheduler/
├── conftest.py               # Carrega o módulo com nome único e define env vars
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes da função lambda_handler()
└── __init__.py
```

## Fixtures (`conftest.py`)

| Fixture | Tipo | Descrição |
|---|---|---|
| `LIGHTSAIL_INSTANCE_NAME` (env var) | `str` | Nome da instância Lightsail simulada (`"test-instance"`) |
| `lambda_lightsail_scheduler_main` (módulo) | `ModuleType` | Módulo carregado via `importlib.util` com nome único para evitar conflito com outros `main.py` |

## Casos de teste — `test_main.py`

### `TestLambdaHandler`

| Teste | O que verifica |
|---|---|
| `test_stop_chama_stop_instance` | Ação `"stop"` chama `stop_instance(instanceName="test-instance")` e retorna `{"status": "stopping", "instance": "test-instance"}` |
| `test_start_chama_start_instance` | Ação `"start"` chama `start_instance(instanceName="test-instance")` e retorna `{"status": "starting", "instance": "test-instance"}` |
| `test_acao_desconhecida_levanta_value_error` | Ação `"restart"` (inválida) levanta `ValueError` |
| `test_sem_instance_name_levanta_key_error` | Quando `LIGHTSAIL_INSTANCE_NAME` não está definida, levanta `KeyError` |

## Como executar

```bash
# Apenas os testes do lambda_lightsail_scheduler
pytest test/lambda_lightsail_scheduler/ -v

# Com cobertura
pytest test/lambda_lightsail_scheduler/ --cov=app/lambda_lightsail_scheduler --cov-report=term-missing
```

## Cobertura mínima

**80%** — definido via `--cov-fail-under=80` no workflow de CI (`.github/workflows/01_test.yml`).
