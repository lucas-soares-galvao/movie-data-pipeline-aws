# scripts — Backfills Manuais

## O que é

Conjunto de scripts Python para operações de backfill sob demanda. Cada script re-processa dados históricos de uma etapa específica do pipeline, invocando os mesmos recursos AWS (Lambda, Glue) que o pipeline automático utiliza.

## Por que existe

O pipeline mensal processa apenas dados novos (delta). Quando é necessário re-processar dados históricos — seja por novos campos, correções de schema, traduções ou validação de qualidade — estes scripts orquestram as chamadas aos serviços AWS de forma controlada, com pausas entre execuções para respeitar limites de concorrência.

## Scripts disponíveis

| Script | Descrição | Serviço AWS | Dependências extras |
|---|---|---|---|
| `backfill_historico.py` | Popula discovers de 2000 até o ano atual via Lambda | Lambda | — |
| `backfill_enriquecimento.py` | Re-busca detalhes com campos enriquecidos (elenco, diretor, keywords) | Glue Details | — |
| `backfill_data_quality.py` | Aciona validação de qualidade para todas as tabelas | Glue Data Quality | — |
| `backfill_traducao.py` | Traduz title/overview para português via Google Translate | S3 (direto) | awswrangler, pandas, deep_translator |

## Como executar

### Via GitHub Actions (recomendado)

1. Ir em **Actions > 5. Backfill > Run workflow**
2. Selecionar o script, ano inicial e ano final
3. Acompanhar logs na aba do workflow

O workflow (`.github/workflows/05_backfill.yml`) autentica via OIDC no ambiente **prod** e configura todas as variáveis de ambiente automaticamente.

### Localmente (requer credenciais AWS configuradas)

```bash
export AWS_REGION=sa-east-1
export GLUE_DETAILS_JOB_NAME=tmdb-glue-details-prod
# ... demais variáveis (ver docstring de cada script)
python scripts/backfill_enriquecimento.py
```

## Variáveis comuns

Todos os scripts aceitam:

| Variável | Padrão | Descrição |
|---|---|---|
| `BACKFILL_START_YEAR` | `2000` | Ano inicial do backfill |
| `BACKFILL_END_YEAR` | ano atual | Ano final do backfill |

Cada script possui variáveis adicionais documentadas em sua docstring.
