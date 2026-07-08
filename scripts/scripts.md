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
| `backfill_traducao.py` | Traduz overview para português via Google Translate | S3 (direto) | awswrangler, pandas, deep_translator |

`backfill_checkpoint.py` não é executado diretamente — é um módulo compartilhado
pelos 4 scripts acima (exceto `backfill_referencias.py`) para o checkpoint de
retomada automática (ver seção "Retomada automática" abaixo).

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

Os 4 scripts que iteram por ano (`backfill_historico.py`, `backfill_enriquecimento.py`,
`backfill_data_quality.py`, `backfill_traducao.py`) também exigem:

| Variável | Descrição |
|---|---|
| `TABLE_GROUP` | Identifica o backfill para o checkpoint de retomada (`discover`, `detalhes_e_providers`, `data_quality`, `traducao`) |
| `S3_BUCKET_SOT` | Bucket onde o checkpoint é armazenado |

Cada script possui variáveis adicionais documentadas em sua docstring.

## Retomada automática (ExpiredTokenException)

Os 4 scripts acima gravam, a cada unidade de trabalho concluída (ano+tipo, ou
tabela+ano), um checkpoint em
`s3://{S3_BUCKET_SOT}/_backfill_checkpoints/{TABLE_GROUP}.json` (ver
`scripts/backfill_checkpoint.py`). Se a credencial AWS expirar no meio do
backfill (`ExpiredTokenException`), o script sai com o exit code 75
(`backfill_checkpoint.RETRYABLE_EXIT_CODE`) em vez de propagar a exceção crua.

O workflow `.github/workflows/05_backfill.yml` reconhece esse código: renova a
credencial (nova sessão de 1h via `sts assume-role-with-web-identity`, usando
o token OIDC do próprio job) e roda o script de novo, dentro do mesmo job —
até 10 tentativas. Como o script relê o checkpoint no início, ele pula direto
para as unidades ainda pendentes em vez de recomeçar do `BACKFILL_START_YEAR`.

Qualquer outro tipo de erro (não relacionado a token expirado) continua
falhando o job normalmente, sem retry automático. O checkpoint só é apagado
quando o backfill termina 100% sem falhas — se sobrarem falhas "soft" (ex.:
um run do Glue Details que terminou em `FAILED`), o checkpoint permanece,
então disparar o workflow de novo com o mesmo range de anos re-tenta só as
unidades que faltaram.
