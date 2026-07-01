# Shared Src — Funções compartilhadas entre componentes do pipeline

## Objetivo

Pacote Python reutilizado por múltiplos jobs Glue e pela Lambda API. Evita duplicação de código entre componentes que precisam das mesmas funções.

## Estrutura

```
app/shared_src/
├── shared_src.md          ← este arquivo
└── shared_utils/          ← pacote Python (importado como shared_utils)
    ├── __init__.py
    ├── api_client.py      ← acesso a APIs externas (retry, Secrets Manager)
    ├── glue_helpers.py    ← utilitários compartilhados de jobs Glue
    ├── traducao.py        ← tradução inglês → português via Google Translate
    └── triggers.py        ← disparo genérico de jobs Glue
```

## Funções

### `shared_utils/api_client.py`

| Função | Responsabilidade |
|---|---|
| `api_get(url, params, max_retries)` | GET com retry/backoff exponencial para lidar com rate limits de APIs (429, 5xx) |
| `get_api_secret(secret_arn, key_name)` | Busca um segredo no AWS Secrets Manager |

### `shared_utils/glue_helpers.py`

| Função | Responsabilidade |
|---|---|
| `get_resolved_option(args)` | Wrapper de `getResolvedOptions` — converte lista de nomes em dicionário nome→valor |
| `configurar_logging_glue()` | Configura logging padrão para jobs Glue (stdout, INFO, formato com timestamp) e retorna o logger raiz |

### `shared_utils/traducao.py`

| Função | Responsabilidade |
|---|---|
| `traduzir_texto(texto, contexto)` | Traduz texto de inglês para português via Google Translate; retorna o original em caso de falha para não interromper o job |

### `shared_utils/triggers.py`

| Função | Responsabilidade |
|---|---|
| `trigger_glue_job(job_name, **arguments)` | Dispara qualquer job Glue (fire-and-forget), convertendo kwargs para o formato `--CHAVE` do Glue |

## Uso nos componentes

| Componente | Funções importadas |
|---|---|
| `lambda_api` | `api_get`, `get_api_secret` |
| `glue_details` | `api_get`, `get_api_secret`, `get_resolved_option`, `traduzir_texto`, `trigger_glue_job` |
| `glue_etl` | `get_resolved_option`, `traduzir_texto`, `trigger_glue_job` |
| `glue_agg` | `get_resolved_option`, `trigger_glue_job` |
| `glue_agg/main` | `configurar_logging_glue` |
| `glue_etl/main` | `configurar_logging_glue` |
| `glue_data_quality/main` | `configurar_logging_glue` |
| `glue_details/main` | `configurar_logging_glue` |

## Deploy

- **Glue jobs**: empacotado como wheel (`tmdb_shared-0.0.0-py3-none-any.whl`) via `build_glue_wheel.py --package shared_utils` e referenciado no `--extra-py-files` de cada job
- **Lambda**: copiado para dentro do zip via `build_lambda_package.py --shared`
- **Terraform**: build e upload em `shared_src.tf`, paths em `locals.tf`
