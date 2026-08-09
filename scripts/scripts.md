# scripts — Backfills Manuais

## O que é

Conjunto de scripts Python para operações de backfill sob demanda. Cada script re-processa dados históricos de uma etapa específica do pipeline. Nenhum dos 8 scripts invoca a Lambda API — a coleta TMDB e a transformação equivalente ao Glue ETL/Glue Details rodam diretamente no processo do script; o único recurso AWS gerenciado ainda acionado como job é o Glue Data Quality (e o Glue AGG, disparado pelo workflow ao final).

## Por que existe

O pipeline mensal processa apenas dados novos (delta). Quando é necessário re-processar dados históricos — seja por novos campos, correções de schema, traduções ou validação de qualidade — estes scripts orquestram as chamadas aos serviços AWS de forma controlada, com pausas entre execuções para respeitar limites de concorrência.

## Scripts disponíveis

| Script | Descrição | Serviço AWS | Dependências extras |
|---|---|---|---|
| `backfill_discover.py` | Popula as tabelas discover de 2000 até o ano atual; roda a coleta TMDB e a transformação equivalente ao Glue ETL diretamente no processo do script (sem acionar Lambda nem o job Glue ETL), usando `TRANSLATE_PROVIDER` (default `google`) só para o detector de idioma do overview. Não dispara o Glue Details — usar `backfill_enriquecimento.py` à parte para popular details/watch_providers. Dispara o Glue Data Quality uma única vez ao final de todo o backfill (não por unidade) | Secrets Manager, TMDB API, S3 (direto), Glue Data Quality | awswrangler, pandas, requests, langdetect |
| `backfill_referencias.py` | Atualiza tabelas de referência (genre, configuration, watch_providers_ref) para movie e tv; roda a coleta TMDB e a transformação equivalente ao Glue ETL diretamente no processo do script (sem acionar Lambda nem o job Glue — ver `app/lambda_api/lambda_api.md`, seção "Backfill manual"); não depende de ano — `configuration` (países/idiomas) traduz via `TRANSLATE_PROVIDER` (default `google`). Dispara o Glue Data Quality uma vez por tabela gravada | Secrets Manager, TMDB API, S3 (direto), Glue Data Quality | awswrangler, pandas, requests, deep_translator, langdetect |
| `backfill_enriquecimento.py` | Re-busca detalhes com campos enriquecidos (elenco, diretor, keywords); roda a lógica de enriquecimento do Glue Details diretamente no processo do script (sem acionar o job Glue — ver `run_details_and_watch_providers_for_year` em `app/glue_details/src/utils.py`), traduzindo via `TRANSLATE_PROVIDER` (default `google`). Dispara o Glue Data Quality uma única vez ao final de todo o backfill (não por unidade) | Athena, Secrets Manager, TMDB API, S3 (direto) | awswrangler, pandas, requests, deep_translator, langdetect |
| `backfill_data_quality.py` | Aciona validação de qualidade para todas as tabelas — único `table_group` que **não** dispara o Glue AGG ao final (não escreve dado novo, só valida) | Glue Data Quality | — |
| `backfill_traducao.py` | Traduz overview, tagline e keywords para português via Google Translate ou AWS Translate (`TRANSLATE_PROVIDER`; não gera collection_name_pt, que depende da API do TMDB) | S3 (direto) | awswrangler, pandas, deep_translator |
| `backfill_rename_colunas.py` | Migra `dt_processamento`/`dt_atualizacao` (nomes legados em português) para `processed_date`/`updated_date` nos parquets de details/watch_providers já gravados no S3 — sem chamar a API do TMDB, cobre inclusive IDs que já saíram do discover atual | S3 (direto) | awswrangler, pandas |
| `backfill_changes.py` | Dispara sob demanda o mesmo modo changes que o cron semanal de domingo já aciona automaticamente — 2 content_types (movie, tv), janela sempre `[domingo passado, sábado de ontem]` (não configurável); roda a coleta de IDs mudados e o enriquecimento diretamente no processo do script (sem acionar Lambda nem o job Glue Details — ver `collect_changes_data`/`process_changed_ids` em `app/glue_details/glue_details.md`, seção "Reuso fora do Glue"), traduzindo via `TRANSLATE_PROVIDER` (default `google`). Dispara o Glue Data Quality uma única vez ao final por tabela (não por ano); útil quando o cron falha ou é pulado | Athena, Secrets Manager, TMDB API, S3 (direto), Glue Data Quality | awswrangler, pandas, requests, deep_translator, langdetect |
| `backfill_historico.py` | Encadeia `backfill_discover.py` e, na sequência, `backfill_enriquecimento.py`, chamando o `main()` de cada um diretamente neste processo (nunca via subprocess) — simula fora do EventBridge o mesmo encadeamento `discover → detalhes/providers` do pipeline automático. Não introduz variável de ambiente nova (união das exigidas pelos dois) nem reimplementa nenhuma lógica de coleta/transformação — só orquestra a ordem. Mantém um checkpoint próprio (`TABLE_GROUP="historico"` interno, unidades `"discover"`/`"enriquecimento"`) por cima dos dois checkpoints internos, para não redigitar um estágio já concluído numa retomada. Se `discover` terminar com falha soft, `enriquecimento` não roda. Herda os 2 disparos de Glue Data Quality dos dois scripts (não dispara um terceiro consolidado) | Secrets Manager, Athena, TMDB API, S3 (direto), Glue Data Quality | mesmas de `backfill_discover.py` + `backfill_enriquecimento.py` |

`backfill_shared.py` não é executado diretamente — é um módulo compartilhado
por todos os 8 scripts acima: leitura de variável de ambiente obrigatória,
setup de logging, leitura do range de anos, proteção de custo do AWS
Translate por intervalo de anos (`apply_translate_cost_guard`), wrapper de
retry do exit code 75 e, para os 5 scripts que iteram por ano diretamente
(todos exceto `backfill_referencias.py`, `backfill_changes.py` e
`backfill_historico.py`), o checkpoint de retomada automática (ver seção
"Retomada automática" abaixo). `backfill_historico.py` não itera por ano
diretamente — delega essa iteração aos dois scripts que encadeia — mas
também usa o checkpoint genérico de `backfill_shared.py`, só que com unidade
"nome do estágio" (`discover`/`enriquecimento`) em vez de "ano+tipo".

## Pré-requisitos

- Python 3.12+ com as dependências do projeto instaladas
- Credenciais AWS configuradas (`aws configure` ou variáveis de ambiente)
- Variáveis de ambiente específicas de cada script documentadas em sua docstring

## Como executar

### Via GitHub Actions (recomendado)

1. Ir em **Actions > 5. Backfill > Run workflow**, escolhendo o branch `main` (prod) ou `develop` (dev) no seletor "Use workflow from" — esse branch determina o ambiente
2. Selecionar o grupo de tabelas (`table_group`), ano inicial e ano final (ambos ignorados para `referencias` e `changes` — `changes` não usa nenhum input de data, é sempre a janela padrão de 7 dias)
3. Acompanhar logs na aba do workflow

O workflow (`.github/workflows/05_backfill.yml`) resolve o ambiente automaticamente pelo branch selecionado, autentica via OIDC no ambiente correspondente e configura todas as variáveis de ambiente automaticamente.

### Localmente (requer credenciais AWS configuradas)

```bash
export AWS_REGION=sa-east-1
export TMDB_SECRET_ARN=arn:aws:secretsmanager:sa-east-1:...:secret:tmdb-api-key-prod
# ... demais variáveis (ver docstring de cada script)
python scripts/backfill_enriquecimento.py
```

## Variáveis comuns

Todos os scripts aceitam, **exceto `backfill_referencias.py` e `backfill_changes.py`** (nenhum dos dois depende de ano — `backfill_changes.py` usa sempre a janela padrão de 7 dias):

| Variável | Padrão | Descrição |
|---|---|---|
| `BACKFILL_START_YEAR` | `2000` | Ano inicial do backfill |
| `BACKFILL_END_YEAR` | ano atual | Ano final do backfill |

Os 5 scripts que iteram por ano (`backfill_discover.py`, `backfill_enriquecimento.py`,
`backfill_data_quality.py`, `backfill_traducao.py`, `backfill_rename_colunas.py`) também exigem:

| Variável | Descrição |
|---|---|
| `TABLE_GROUP` | Identifica o backfill para o checkpoint de retomada (`discover`, `detalhes_e_providers`, `data_quality`, `traducao`, `rename_colunas`) |
| `S3_BUCKET_TEMP` | Bucket onde o checkpoint é armazenado (dados temporários, não os dados reais do pipeline) |

`backfill_discover.py` exige adicionalmente `S3_BUCKET_SOR` (JSON bruto de
discover, mesmo bucket usado por `backfill_referencias.py` para as tabelas de
referência), `S3_BUCKET_SOT` (parquets das tabelas discover),
`TABLE_DISCOVER_MOVIE`/`TABLE_DISCOVER_TV`, `TMDB_SECRET_ARN` e
`GLUE_DATA_QUALITY_JOB_NAME` — mesmo padrão de variáveis extras de
`backfill_enriquecimento.py`, já que ambos rodam a coleta/transformação
diretamente no processo em vez de delegar a um recurso gerenciado.

`backfill_changes.py` exige `AWS_REGION`, `GLUE_DATABASE_MOVIE`/`GLUE_DATABASE_TV`,
`TABLE_DISCOVER_MOVIE`/`TABLE_DISCOVER_TV`, `TABLE_DETAILS_MOVIE`/`TABLE_DETAILS_TV`,
`TABLE_WATCH_PROVIDERS_MOVIE`/`TABLE_WATCH_PROVIDERS_TV`, `S3_BUCKET_SOT`,
`S3_BUCKET_TEMP`, `TMDB_SECRET_ARN`, `GLUE_DATA_QUALITY_JOB_NAME` e,
opcionalmente, `TRANSLATE_PROVIDER` — sem `TABLE_GROUP` (não grava checkpoint,
ver "Retomada automática" abaixo). `S3_BUCKET_TEMP` aqui **não** é para
checkpoint (que este script não tem) — é o handoff efêmero da lista de IDs
mudados (`tmdb/changes/{content_type}/{data}.json`), mesmo bucket/prefixo que
o modo changes automático (via Lambda) já usa. Fica fora da proteção de custo
`apply_translate_cost_guard` (ver abaixo) pelo mesmo motivo que sempre esteve:
o volume do modo changes é limitado aos IDs que a própria TMDB reporta como
alterados na janela de 7 dias, não o catálogo inteiro.

`backfill_traducao.py` exige adicionalmente `S3_BUCKET_SOT`, usado para ler e
escrever os parquets reais de `tb_discover_movie/tv_tmdb` e
`tb_details_movie/tv_tmdb` — separado do checkpoint, que fica no bucket TEMP
como os demais.

`backfill_rename_colunas.py` também exige `S3_BUCKET_SOT` (mesmo motivo) e,
adicionalmente, `TABLE_WATCH_PROVIDERS_MOVIE`/`TABLE_WATCH_PROVIDERS_TV` (além
de `TABLE_DETAILS_MOVIE`/`TABLE_DETAILS_TV`, já usadas por `backfill_traducao.py`).

`backfill_historico.py` exige `AWS_REGION` e `S3_BUCKET_TEMP` diretamente (para
o próprio checkpoint de estágio) e, indiretamente, todas as variáveis de
`backfill_discover.py` e `backfill_enriquecimento.py` (lidas por cada `main()`
quando chamado) — nenhuma variável nova. Diferente dos demais, **não** lê
`TABLE_GROUP` do ambiente — define `"discover"` e depois
`"detalhes_e_providers"` internamente antes de chamar cada estágio, então
`TABLE_GROUP` não deve ser passada por quem chama este script.

`backfill_referencias.py` exige `AWS_REGION`, `S3_BUCKET_SOR`, `S3_BUCKET_SOT`,
`GLUE_DATABASE_MOVIE`/`GLUE_DATABASE_TV`, `TABLE_GENRE_MOVIE`/`TABLE_GENRE_TV`,
`TABLE_CONFIGURATION_LANGUAGES`/`TABLE_CONFIGURATION_COUNTRIES`,
`TABLE_WATCH_PROVIDERS_REF_MOVIE`/`TABLE_WATCH_PROVIDERS_REF_TV`,
`TMDB_SECRET_ARN`, `GLUE_DATA_QUALITY_JOB_NAME` e, opcionalmente,
`TRANSLATE_PROVIDER` — sem `TABLE_GROUP` (não grava checkpoint, mesmo motivo
de `backfill_changes.py`: poucas unidades, sem dependência de ano).
`S3_BUCKET_SOR` é exclusivo deste script — nenhum outro grava JSON bruto
diretamente (os demais só leem/escrevem parquet no SOT).

Todos os backfills que traduzem ou detectam idioma (`backfill_discover.py`,
`backfill_enriquecimento.py`, `backfill_referencias.py`, `backfill_traducao.py`
e `backfill_changes.py`, todos via env var própria) aceitam opcionalmente
`TRANSLATE_PROVIDER` (default `"google"` — grátis, mas
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
`langdetect` como fallback. `backfill_discover.py` resolve `detect_fn` uma
única vez antes do loop (não traduz nenhum campo — só sinaliza o idioma do
overview), enquanto `backfill_enriquecimento.py`, `backfill_referencias.py`,
`backfill_traducao.py` e `backfill_changes.py` resolvem
`resolve_translate_fn`/`resolve_detect_language_fn` (ou, no caso de
`backfill_enriquecimento.py`/`backfill_changes.py`, o `translate_provider`
recebido por `collect_and_write_details` dentro de
`run_details_and_watch_providers_for_year`/`process_changed_ids`) a cada
partição ano+tipo (ou content_type, no caso de
`backfill_referencias.py`/`backfill_changes.py`), para que a primeira
partição processada não esgote sozinha o orçamento de fallback ao AWS
Translate de todo o backfill. Todos rodam suas partições dentro do mesmo
processo Python — nenhum invoca a Lambda API.

**Proteção de custo por intervalo de anos:** nos 3 backfills que iteram por
ano e dependem disso (`backfill_discover.py`, `backfill_enriquecimento.py`,
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

`backfill_changes.py` e `backfill_referencias.py` também saem com exit code
75 em caso de token expirado (fazem chamadas reais de S3/Secrets Manager/TMDB
API — e Athena, no caso de `backfill_changes.py` — no processo, não mais uma
única invocação curta de Lambda) e são retomados pelo mesmo loop genérico do
workflow — mas **sem checkpoint**: poucas unidades (2 em `backfill_changes.py`,
6 em `backfill_referencias.py`), e as funções chamadas em ambos são
idempotentes, então a retomada simplesmente refaz tudo do zero em vez de
pular direto para o pendente.

`backfill_historico.py` não grava checkpoint por ano/tipo — quem faz isso são
`backfill_discover.py`/`backfill_enriquecimento.py`, chamados por ele. Mantém
só um checkpoint de estágio próprio
(`s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/historico.json`, unidades
`"discover"`/`"enriquecimento"`), usado para pular um estágio inteiro que já
terminou sem falhas (e por isso já limpou seu próprio checkpoint por
ano/tipo) numa retomada — sem esse marcador, retomar depois de uma falha no
segundo estágio reprocessaria o primeiro inteiro do zero. Um `ClientError` de
token expirado levantado dentro de qualquer um dos dois estágios propaga
normalmente até o `run_with_retry_exit` do próprio `backfill_historico.py`
(exit code 75, mesmo contrato).

Qualquer outro tipo de erro (não relacionado a token expirado) continua
falhando o job normalmente, sem retry automático. O checkpoint só é apagado
quando o backfill termina 100% sem falhas — se sobrarem falhas "soft" (ex.:
uma exceção não fatal ao processar uma unidade em `backfill_discover.py`/
`backfill_enriquecimento.py`), o checkpoint permanece, então disparar o
workflow de novo com o mesmo range de anos re-tenta só as unidades que
faltaram. Em `backfill_discover.py`, `backfill_enriquecimento.py` e
`backfill_changes.py`, o Glue Data Quality também só é disparado (uma vez, ao
final, por tabela) quando não sobra nenhuma falha — um range/content_type com
unidades pendentes não é validado até ser reprocessado com sucesso
(`backfill_changes.py` não tem checkpoint, então "reprocessado" aqui
significa disparar o workflow de novo do zero, não retomar de onde parou).

## Step summary: resumo do backfill e disparo do Glue AGG ao final

Depois que o loop de retry termina com sucesso (`exit 0`), o workflow
(`.github/workflows/05_backfill.yml`) escreve duas seções no step summary do
GitHub Actions, nessa ordem:

1. **"Backfill"** — o resumo real do que o script fez, extraído do log via
   `grep` (todos os 8 scripts usam o mesmo formato de log,
   `backfill_shared.py:58-63`: `"%(asctime)s %(levelname)s %(message)s"`, com
   `%(asctime)s` em horário de São Paulo (`DD/MM/YYYY HH:MM:SS`) via
   `Formatter.converter`/`datefmt` customizados em `backfill_shared.py`).
   Isso importa porque `exit 0` **não** garante que toda unidade teve
   sucesso para 5 dos 8 scripts: `backfill_discover.py`,
   `backfill_enriquecimento.py` e `backfill_changes.py` são soft-fail-continue
   (logam `ERROR` por unidade/content_type que falhou, mas nunca chamam
   `sys.exit`), `backfill_data_quality.py` é fire-and-forget ("submetido" ≠
   "validado" — ver `especialista-scripts-backfill`), e `backfill_historico.py`
   herda o soft-fail-continue de `backfill_discover.py`/
   `backfill_enriquecimento.py` (interrompe entre estágios em caso de falha,
   mas o processo em si sai com `exit 0`). Se sobrar qualquer
   linha `ERROR` no log, o step summary mostra "⚠️ Falhas parciais
   registradas" com as linhas encontradas, mesmo com o job do Actions
   terminando verde.
2. **"glue_agg"** — o AGG roda em agendamento próprio (sábado e domingo às
   08:00 BRT — ver `app/glue_agg/glue_agg.md`), desacoplado do pipeline
   automático. Para o backfill manual, essa espera (até 6 dias) é
   indesejada: o workflow dispara `glue:StartJobRun` uma única vez para
   **todo `table_group` exceto `data_quality`** (que não escreve dado novo)
   e faz polling do `JobRunId` (`glue:GetJobRun` a cada 30s) até um estado
   terminal, escrevendo `SUCCEEDED`/`FAILED`/`STOPPED`/`ERROR`/`TIMEOUT` no
   step summary.

O disparo/polling do AGG é centralizado no workflow, não em cada script,
para garantir que rode exatamente uma vez por execução mesmo quando o
script precisou de retomada via exit code 75. Nem uma falha ao disparar nem
uma conclusão diferente de `SUCCEEDED` derrubam o workflow — loga um
`::warning::` e segue: o trigger agendado do fim de semana e o alarme SNS
dedicado (`aws_cloudwatch_event_rule.glue_agg_failed`,
`infra/cloudwatch_glue_alarms.tf`) continuam cobrindo o caso.
