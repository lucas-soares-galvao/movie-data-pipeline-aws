# Pipeline e Observabilidade

## Agendamento — EventBridge (`eventbridge.tf`)

7 regras de schedule, separadas por tipo de mídia e frequência. Os horários são espaçados com gap de 30 min entre semanal e mensal para evitar `ConcurrentModificationException` no Glue Catalog quando dois jobs Details tocam a mesma partição:

| Regra | Frequência | Horário | Comportamento |
|---|---|---|---|
| `lambda_api_movie_weekly` | Semanal (dom) | 06:00 BRT (09:00 UTC) | `only_weekly_tables=true` — filmes novos + now_playing |
| `lambda_api_tv_weekly` | Semanal (dom) | 06:05 BRT (09:05 UTC) | `only_weekly_tables=true` — séries novas |
| `lambda_api_movie_changes_weekly` | Semanal (sáb) | 06:00 BRT (09:00 UTC) | `only_changes_tables=true` — refresh de filmes já catalogados (Changes API), qualquer ano |
| `lambda_api_tv_changes_weekly` | Semanal (sáb) | 06:05 BRT (09:05 UTC) | `only_changes_tables=true` — refresh de séries já catalogadas (Changes API), qualquer ano |
| `lambda_api_movie_monthly` | Dia 1 do mês | 06:30 BRT (09:30 UTC) | `only_monthly_tables=true` — referências + discover do ano anterior |
| `lambda_api_tv_monthly` | Dia 1 do mês | 06:35 BRT (09:35 UTC) | `only_monthly_tables=true` — referências + discover do ano anterior |
| `sfn_backfill_annual` | 1 de jan (anual) | 07:00 BRT (10:00 UTC) | **DISABLED** — inicia o Step Function de backfill histórico com `{"start_year": 2000}`, mas o disparo automático está desativado (reprocessar desde 2000 todo ano era gasto desnecessário); start apenas manual |

As regras de changes rodam no sábado — um dia inteiro antes do discover semanal de domingo, mesmo horário — para que os dois ciclos de Glue Details (changes e discover) nunca concorram pelo rate limit do TMDB. Diferente do modo semanal/mensal (que só cobrem o ano atual e o anterior), o modo changes usa `/movie/changes`/`/tv/changes` do TMDB para detectar títulos alterados em **qualquer** ano de lançamento — fecha o gap de staleness em todo o catálogo histórico sem re-rodar `/discover`. Ver `app/lambda_api/lambda_api.md` e `app/glue_details/glue_details.md` ("Modo changes").

**Dead Letter Queue (DLQ):** todos os targets do EventBridge (pipeline e Lightsail scheduler) enviam eventos não entregues para a fila SQS `tmdb-eventbridge-dlq-{env}` (`sqs.tf`), com retenção de 14 dias. Um alarme CloudWatch monitora a fila e notifica via SNS (tópico de falha do EventBridge) quando há mensagens.

## Orquestração — Step Functions (`step_functions.tf`)

State machine `tmdb-sfn-backfill-{env}` para coleta histórica de dados ano a ano, contornando o limite de 15 minutos da Lambda.

**Acionamento:** manual apenas. A regra EventBridge `sfn_backfill_annual` (1º de janeiro às 10:00 UTC, input `{"start_year": 2000}`) existe mas está `DISABLED` — cada execução reprocessa o backfill inteiro desde 2000, o que se mostrou desnecessário/custoso rodar automaticamente todo ano. Para rodar sob demanda: Step Functions → `tmdb-sfn-backfill-{env}` → Start Execution.

**Logging:** habilitado com nível `ALL` e `include_execution_data = true`, enviando logs para o CloudWatch Log Group `/aws/vendedlogs/states/tmdb-sfn-backfill-{env}`.

**Fluxo da execução:**

1. **GenerateYears** (Pass) — extrai o ano do timestamp de execução, converte para inteiro e subtrai 2 (`end_year`)
2. **ComputeYears** (Pass) — gera o array `[start_year, ..., end_year]` via `States.ArrayRange`
3. **CreateBatches** (Pass) — divide o array de anos em sub-arrays de 1 elemento via `States.ArrayPartition` (ex: `[2000,2001,2002]` → `[[2000],[2001],[2002]]`)
4. **ProcessBatches** (Map, `MaxConcurrency=1`) — itera cada batch sequencialmente:
   - **InvokeLambdaMovie** — invoca a Lambda com payload de filmes para o batch (Retry: 2 tentativas, intervalo de 30s, backoff 2.0)
   - **WaitBeforeTV** — aguarda 5 min para o Glue Details terminar antes de iniciar séries
   - **InvokeLambdaTV** — invoca a Lambda com payload de séries para o batch (Retry: 2 tentativas, intervalo de 30s, backoff 2.0)
   - **WaitBeforeNextBatch** — aguarda 5 min antes do próximo batch

> Hoje o backfill é sempre manual: via console/CLI da state machine (backfill completo desde um `start_year`) ou via workflow `05_backfill.yml` (GitHub Actions, `workflow_dispatch`), que dispara scripts Python diretamente contra a Lambda API e os jobs Glue Details/Data Quality, sem passar pela state machine — usado para correções pontuais em um grupo específico de tabelas. O ambiente (dev/prod) é resolvido automaticamente pelo branch selecionado ao disparar o workflow (ver `overview.md`).

## Notificações — SNS (`sns_topics.tf`)

9 tópicos SNS, um por evento relevante do pipeline. Cada tópico envia alertas para um e-mail configurado em `.tfvars`:

| Tópico | Evento |
|---|---|
| `tmdb-lambda-failure-notifications-{env}` | Falha na Lambda API |
| `tmdb-eventbridge-failure-notifications-{env}` | Falha no agendamento EventBridge |
| `tmdb-glue-etl-failure-notifications-{env}` | Falha no job ETL |
| `tmdb-glue-details-failure-notifications-{env}` | Falha no job Details |
| `tmdb-glue-agg-failure-notifications-{env}` | Falha no job AGG |
| `tmdb-glue-agg-success-notifications-{env}` | Sucesso do job AGG |
| `tmdb-glue-data-quality-failure-notifications-{env}` | Falha nas regras de DQ |
| `tmdb-glue-data-quality-metrics-notifications-{env}` | Métricas de DQ (resultados das regras) |
| `tmdb-sfn-backfill-failure-notifications-{env}` | Falha no Step Functions Backfill (FAILED, TIMED_OUT, ABORTED) |

> Antes desta mudança, os tópicos SNS eram globais (sem sufixo de ambiente) — se dev e prod estivessem na mesma conta AWS, dividiriam o mesmo tópico/inscrição de e-mail. Agora cada ambiente tem seus próprios tópicos.

## Observabilidade — CloudWatch (`cloudwatch_alarms.tf`, `cloudwatch_glue_alarms.tf`, `cloudwatch_logs.tf`)

- **Alarmes** para cada job Glue e para a Lambda (falhas, timeouts)
- **Alarmes de métricas DQ** para o Glue Data Quality (regras com falha)
- **Log groups** para Lambda, Glue, Step Functions e Lightsail (FilmBot) com retenção configurável:
  - `dev`: 1 dia (reduz custo)
  - `prod`: 5 dias (permite investigar incidentes)
