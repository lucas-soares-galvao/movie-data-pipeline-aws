# scripts — Backfills Manuais

## O que é

Conjunto de scripts Python para operações de backfill sob demanda. Cada script re-processa dados históricos de uma etapa específica do pipeline, invocando os mesmos recursos AWS (Lambda, Glue) que o pipeline automático utiliza.

## Por que existe

O pipeline mensal processa apenas dados novos (delta). Quando é necessário re-processar dados históricos — seja por novos campos, correções de schema, traduções ou validação de qualidade — estes scripts orquestram as chamadas aos serviços AWS de forma controlada, com pausas entre execuções para respeitar limites de concorrência.

## Scripts disponíveis

| Script | Descrição | Serviço AWS | Dependências extras |
|---|---|---|---|
| `backfill_historico.py` | Popula discovers de 2000 até o ano atual via Lambda | Lambda | — |
| `backfill_referencias.py` | Atualiza tabelas de referência (genre, configuration, watch_providers_ref) para movie e tv via Lambda; não depende de ano | Lambda | — |
| `backfill_enriquecimento.py` | Re-busca detalhes com campos enriquecidos (elenco, diretor, keywords) | Glue Details | — |
| `backfill_data_quality.py` | Aciona validação de qualidade para todas as tabelas | Glue Data Quality | — |
| `backfill_traducao.py` | Traduz title/overview para português via Google Translate | S3 (direto) | awswrangler, pandas, deep_translator |

## Pré-requisitos

- Python 3.12+ com as dependências do projeto instaladas
- Credenciais AWS configuradas (`aws configure` ou variáveis de ambiente)
- Variáveis de ambiente específicas de cada script documentadas em sua docstring

## Como executar

### Via GitHub Actions (recomendado)

1. Ir em **Actions > 5. Backfill > Run workflow**, escolhendo o branch `main` (prod) ou `develop` (dev) no seletor "Use workflow from" — esse branch determina o ambiente
2. Selecionar o grupo de tabelas (`table_group`), ano inicial e ano final (ambos ignorados para `referencias`)
3. Acompanhar logs na aba do workflow

O workflow (`.github/workflows/05_backfill.yml`) resolve o ambiente automaticamente pelo branch selecionado, autentica via OIDC no ambiente correspondente e configura todas as variáveis de ambiente automaticamente.

### Localmente (requer credenciais AWS configuradas)

```bash
export AWS_REGION=sa-east-1
export GLUE_DETAILS_JOB_NAME=tmdb-glue-details-prod
# ... demais variáveis (ver docstring de cada script)
python scripts/backfill_enriquecimento.py
```

## Variáveis comuns

Todos os scripts aceitam, **exceto `backfill_referencias.py`** (que não depende de ano e ignora ambas):

| Variável | Padrão | Descrição |
|---|---|---|
| `BACKFILL_START_YEAR` | `2000` | Ano inicial do backfill |
| `BACKFILL_END_YEAR` | ano atual | Ano final do backfill |

Cada script possui variáveis adicionais documentadas em sua docstring.
