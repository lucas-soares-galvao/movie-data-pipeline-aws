# scripts — Backfills Manuais

## O que é

Conjunto de scripts Python para operações de backfill sob demanda. Cada script re-processa dados históricos de uma etapa específica do pipeline, invocando os mesmos recursos AWS (Lambda, Glue) que o pipeline automático utiliza.

## Por que existe

O pipeline mensal processa apenas dados novos (delta). Quando é necessário re-processar dados históricos — seja por novos campos, correções de schema, traduções ou validação de qualidade — estes scripts orquestram as chamadas aos serviços AWS de forma controlada, com pausas entre execuções para respeitar limites de concorrência.

## Scripts disponíveis

| Script | Descrição | Serviço AWS | Dependências extras |
|---|---|---|---|
| `backfill_historico.py` | Popula discovers de 2000 até o ano atual via Lambda — cada invocação aciona Glue ETL → Glue Details, que traduzem via `TRANSLATE_PROVIDER` (default `google`) | Lambda | — |
| `backfill_referencias.py` | Atualiza tabelas de referência (genre, configuration, watch_providers_ref) para movie e tv via Lambda; não depende de ano — `configuration` (países/idiomas) traduz via `TRANSLATE_PROVIDER` (default `google`) | Lambda | — |
| `backfill_enriquecimento.py` | Re-busca detalhes com campos enriquecidos (elenco, diretor, keywords); dispara o Glue Details diretamente, que traduz via `TRANSLATE_PROVIDER` (default `google`) | Glue Details | — |
| `backfill_data_quality.py` | Aciona validação de qualidade para todas as tabelas | Glue Data Quality | — |
| `backfill_traducao.py` | Traduz overview, tagline e keywords para português via Google Translate ou AWS Translate (`TRANSLATE_PROVIDER`; não gera collection_name_pt, que depende da API do TMDB) | S3 (direto) | awswrangler, pandas, deep_translator |
| `backfill_rename_colunas.py` | Migra `dt_processamento`/`dt_atualizacao` (nomes legados em português) para `processed_date`/`updated_date` nos parquets de details/watch_providers já gravados no S3 — sem chamar a API do TMDB, cobre inclusive IDs que já saíram do discover atual | S3 (direto) | awswrangler, pandas |

`backfill_shared.py` não é executado diretamente — é um módulo compartilhado
por todos os 6 scripts acima: leitura de variável de ambiente obrigatória,
setup de logging, invocação síncrona da Lambda API, payloads base de
movie/tv, leitura do range de anos, proteção de custo do AWS Translate por
intervalo de anos (`apply_translate_cost_guard`), wrapper de retry do exit
code 75 e, para os 5 scripts que iteram por ano (todos exceto
`backfill_referencias.py`), o checkpoint de retomada automática (ver seção
"Retomada automática" abaixo).

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

Os 5 scripts que iteram por ano (`backfill_historico.py`, `backfill_enriquecimento.py`,
`backfill_data_quality.py`, `backfill_traducao.py`, `backfill_rename_colunas.py`) também exigem:

| Variável | Descrição |
|---|---|
| `TABLE_GROUP` | Identifica o backfill para o checkpoint de retomada (`discover`, `detalhes_e_providers`, `data_quality`, `traducao`, `rename_colunas`) |
| `S3_BUCKET_TEMP` | Bucket onde o checkpoint é armazenado (dados temporários, não os dados reais do pipeline) |

`backfill_traducao.py` exige adicionalmente `S3_BUCKET_SOT`, usado para ler e
escrever os parquets reais de `tb_discover_movie/tv_tmdb` e
`tb_details_movie/tv_tmdb` — separado do checkpoint, que fica no bucket TEMP
como os demais.

`backfill_rename_colunas.py` também exige `S3_BUCKET_SOT` (mesmo motivo) e,
adicionalmente, `TABLE_WATCH_PROVIDERS_MOVIE`/`TABLE_WATCH_PROVIDERS_TV` (além
de `TABLE_DETAILS_MOVIE`/`TABLE_DETAILS_TV`, já usadas por `backfill_traducao.py`).

Todos os backfills que traduzem (`backfill_historico.py` e
`backfill_referencias.py`, via `backfill_shared.build_base_payloads()`;
`backfill_enriquecimento.py` e `backfill_traducao.py`, via env var própria)
aceitam opcionalmente `TRANSLATE_PROVIDER` (default `"google"` — grátis, mas
instável sob alto volume; `"aws"` usa AWS Translate, pago por caractere, útil
para testar um período menor via `BACKFILL_START_YEAR`/`BACKFILL_END_YEAR`) —
exposto no workflow como o input `translate_provider`. `"google"` também é o
default do caminho automático via EventBridge (`lambda_api` → `glue_etl` →
`glue_details`) — em ambos os casos o serviço não escolhido é usado
automaticamente como fallback caso o primário falhe (ver `resolve_translate_fn`
em `shared_utils.traducao`), com o fallback ao AWS Translate limitado por um
orçamento de caracteres (é pago por caractere). `TRANSLATE_PROVIDER` também
determina o detector de idioma primário (`resolve_detect_language_fn` em
`shared_utils.idioma`): `"google"` usa `langdetect` primeiro com Comprehend como
fallback capado por caracteres; `"aws"` usa Comprehend primeiro (sem cap) com
`langdetect` como fallback. Em `backfill_historico.py`/
`backfill_referencias.py` (via Lambda) e `backfill_enriquecimento.py` (via Glue),
cada partição ano+tipo é uma invocação separada, então "por execução" já
equivale a "por partição". Em `backfill_traducao.py` — o único que itera todas
as partições dentro de um mesmo processo Python — o orçamento é recriado a cada
partição ano+tipo, para que a primeira partição processada não esgote sozinha o
fallback de todo o backfill.

**Proteção de custo por intervalo de anos:** nos 3 backfills que iteram por
ano e dependem disso (`backfill_historico.py`, `backfill_enriquecimento.py`,
`backfill_traducao.py`), se `TRANSLATE_PROVIDER=aws` for escolhido mas o
intervalo (`BACKFILL_START_YEAR`/`BACKFILL_END_YEAR`) cobrir mais de 1 ano, o
provider é rebaixado automaticamente para `"google"` (com um aviso no log) —
ver `backfill_shared.apply_translate_cost_guard()`. Protege contra o cenário
de escolher `"aws"` para testar um período curto e esquecer de voltar para
`"google"` antes de disparar um backfill do catálogo histórico inteiro.
`backfill_referencias.py` fica fora dessa proteção por não depender de ano
(volume sempre pequeno, ~250 itens).

Cada script possui variáveis adicionais documentadas em sua docstring.

## Retomada automática (token expirado)

Os 5 scripts acima gravam, a cada unidade de trabalho concluída (ano+tipo, ou
tabela+ano), um checkpoint em
`s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{TABLE_GROUP}.json` (ver
`scripts/backfill_shared.py`). Se a credencial AWS expirar no meio do
backfill, o script sai com o exit code 75
(`backfill_shared.RETRYABLE_EXIT_CODE`) em vez de propagar a exceção crua.
`backfill_shared.is_expired_token_error()` reconhece os dois códigos de
erro que a AWS usa para credencial expirada: `ExpiredTokenException` (STS —
ex.: chamadas de Lambda/Glue) e `ExpiredToken` (S3 — ex.: `ListObjectsV2` via
awswrangler, `get_object`/`put_object`/`delete_object`).

O workflow `.github/workflows/05_backfill.yml` reconhece esse código: renova a
credencial (nova sessão de 1h via `sts assume-role-with-web-identity`, usando
o token OIDC do próprio job) e roda o script de novo, dentro do mesmo job —
até 6 tentativas (alinhado ao timeout de 360min do job / ~1h por sessão AWS).
Como o script relê o checkpoint no início, ele pula direto
para as unidades ainda pendentes em vez de recomeçar do `BACKFILL_START_YEAR`.

Qualquer outro tipo de erro (não relacionado a token expirado) continua
falhando o job normalmente, sem retry automático. O checkpoint só é apagado
quando o backfill termina 100% sem falhas — se sobrarem falhas "soft" (ex.:
um run do Glue Details que terminou em `FAILED`), o checkpoint permanece,
então disparar o workflow de novo com o mesmo range de anos re-tenta só as
unidades que faltaram.
