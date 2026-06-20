# Shared Src — Funções compartilhadas entre componentes do pipeline

## Objetivo

Pacote Python reutilizado por múltiplos jobs Glue e pela Lambda API. Evita duplicação de código entre componentes que precisam das mesmas funções.

## Estrutura

```
app/shared_src/
├── shared_src.md          ← este arquivo
└── shared_utils/          ← pacote Python (importado como shared_utils)
    ├── __init__.py
    ├── tmdb_api.py        ← acesso à API TMDB (retry, Secrets Manager)
    └── triggers.py        ← disparo genérico de jobs Glue
```

## Funções

### `shared_utils/tmdb_api.py`

| Função | Responsabilidade |
|---|---|
| `tmdb_get(url, params, max_retries)` | GET com retry/backoff exponencial para lidar com rate limits da API TMDB (429, 5xx) |
| `get_tmdb_api_key(secret_arn)` | Busca a chave de API do TMDB no AWS Secrets Manager |

### `shared_utils/triggers.py`

| Função | Responsabilidade |
|---|---|
| `trigger_glue_job(job_name, **arguments)` | Dispara qualquer job Glue (fire-and-forget), convertendo kwargs para o formato `--CHAVE` do Glue |

## Uso nos componentes

| Componente | Funções importadas |
|---|---|
| `lambda_api` | `tmdb_get`, `get_tmdb_api_key` |
| `glue_details` | `tmdb_get`, `get_tmdb_api_key`, `trigger_glue_job` |
| `glue_etl` | `trigger_glue_job` |
| `glue_agg` | `trigger_glue_job` |

## Deploy

- **Glue jobs**: empacotado como wheel (`tmdb_shared-0.0.0-py3-none-any.whl`) via `build_glue_wheel.py --package shared_utils` e referenciado no `--extra-py-files` de cada job
- **Lambda**: copiado para dentro do zip via `build_lambda_package.py --shared`
- **Terraform**: build e upload em `shared_src.tf`, paths em `locals.tf`
