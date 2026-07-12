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
    ├── traducao.py        ← tradução para português via Google Translate (detecção automática de idioma)
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
| `traduzir_texto(texto, contexto)` | Traduz texto para português via Google Translate com detecção automática do idioma de origem (`source="auto"`), com backoff entre tentativas (mesmo padrão de `api_get`); uma exceção usa o orçamento completo de 5 tentativas (tende a ser transitório — rede, rate limit), enquanto um resultado idêntico ao original sem exceção desiste em só 2 (normalmente indica que não há o que traduzir — nome próprio, termo emprestado — não bloqueio); retorna o original se as tentativas se esgotarem, para não interromper o job |
| `traduzir_em_paralelo(valores, traduzir_fn, max_workers)` | Aplica `traduzir_fn` a cada item de `valores` em paralelo via `ThreadPoolExecutor`; recebe a função de tradução como parâmetro (em vez de chamar `traduzir_texto` diretamente) para que os chamadores continuem passando sua própria referência local, preservando os mocks de teste existentes em `glue_details` e `backfill_traducao.py` |
| `traduzir_coluna_pendente(df, coluna_fonte, coluna_destino, mask_elegivel, traduzir_fn, max_workers)` | Orquestra a tradução de `coluna_fonte` → `coluna_destino` para os registros elegíveis ainda pendentes: pula registros com `coluna_destino` preenchida e diferente de `coluna_fonte` (já traduzidos — nativo do TMDB ou run anterior), retenta os que ficaram iguais à fonte (fallback de uma tradução que falhou — ver `traduzir_texto`), grava o resultado via `traduzir_em_paralelo` e devolve a contagem de sucesso. Substitui a lógica que antes estava duplicada (com pequenas divergências) em `glue_details/src/utils.py` e `scripts/backfill_traducao.py` |
| `elegivel_overview_pt(df)` | Mask de candidatos à tradução de overview: `original_language != 'pt'` e `overview_en` não-vazio. Compartilhada entre `glue_details` e `scripts/backfill_traducao.py` |
| `elegivel_tagline_pt(df)` | Mask de candidatos à tradução de tagline: campo não-vazio e `original_language != 'pt'`. Compartilhada entre `glue_details` e `scripts/backfill_traducao.py` |
| `elegivel_keywords_pt(df)` | Mask de candidatos à tradução de keywords: campo não-vazio e `original_language != 'pt'` (TMDB sempre devolve keywords em inglês para os demais idiomas; pular pt evita tradução à toa). Compartilhada entre `glue_details` e `scripts/backfill_traducao.py` |

### `shared_utils/triggers.py`

| Função | Responsabilidade |
|---|---|
| `trigger_glue_job(job_name, **arguments)` | Dispara qualquer job Glue (fire-and-forget), convertendo kwargs para o formato `--CHAVE` do Glue |

## Uso nos componentes

| Componente | Funções importadas |
|---|---|
| `lambda_api` | `api_get`, `get_api_secret`, `trigger_glue_job` |
| `glue_details` | `api_get`, `get_api_secret`, `get_resolved_option`, `traduzir_texto`, `traduzir_coluna_pendente`, `elegivel_overview_pt`, `elegivel_tagline_pt`, `elegivel_keywords_pt`, `trigger_glue_job` |
| `glue_etl` | `get_resolved_option`, `traduzir_texto`, `trigger_glue_job` |
| `scripts/backfill_traducao.py` | `traduzir_texto`, `traduzir_coluna_pendente`, `elegivel_overview_pt`, `elegivel_tagline_pt`, `elegivel_keywords_pt` |
| `glue_agg` | `get_resolved_option`, `trigger_glue_job` |
| `glue_agg/main` | `configurar_logging_glue` |
| `glue_etl/main` | `configurar_logging_glue` |
| `glue_data_quality/main` | `configurar_logging_glue` |
| `glue_details/main` | `configurar_logging_glue` |

## Deploy

- **Glue jobs**: empacotado como wheel (`tmdb_shared-0.0.0-py3-none-any.whl`) via `build_glue_wheel.py --package shared_utils` e referenciado no `--extra-py-files` de cada job
- **Lambda**: copiado para dentro do zip via `build_lambda_package.py --shared`
- **Terraform**: build e upload em `shared_src.tf`, paths em `locals.tf`
