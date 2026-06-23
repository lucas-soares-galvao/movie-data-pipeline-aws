# Pipeline e Observabilidade

## Agendamento — EventBridge (`eventbridge.tf`)

5 regras de schedule, separadas por tipo de mídia e frequência:

| Regra | Frequência | Horário | Comportamento |
|---|---|---|---|
| `lambda_api_movie_weekly` | Semanal (dom) | 07:00 BRT (10:00 UTC) | `only_discover=true` — filmes novos + now_playing |
| `lambda_api_tv_weekly` | Semanal (dom) | 07:05 BRT (10:05 UTC) | `only_discover=true` — séries novas |
| `lambda_api_movie_monthly` | Dia 1 do mês | 07:00 BRT (10:00 UTC) | `skip_weekly=true` — atualiza gêneros, idiomas, plataformas |
| `lambda_api_tv_monthly` | Dia 1 do mês | 07:05 BRT (10:05 UTC) | `skip_weekly=true` — atualiza gêneros, países, plataformas |
| `sfn_backfill_annual` | 1 de jan (anual) | 07:30 BR (10:30 UTC) | Inicia o Step Function de backfill histórico com `{"start_year": 2000}` |

**Dead Letter Queue (DLQ):** todos os targets do EventBridge (pipeline e Lightsail scheduler) enviam eventos não entregues para a fila SQS `tmdb-eventbridge-dlq-{env}` (`sqs.tf`), com retenção de 14 dias. Um alarme CloudWatch monitora a fila e notifica via SNS (tópico de falha do EventBridge) quando há mensagens.

## Orquestração — Step Functions (`step_functions.tf`)

State machine `tmdb-sfn-backfill-{env}` para coleta histórica de dados ano a ano, contornando o limite de 15 minutos da Lambda.

**Acionamento:** regra EventBridge `sfn_backfill_annual` no dia 1º de janeiro às 10:30 UTC, com input `{"start_year": 2000}`.

**Logging:** habilitado com nível `ALL` e `include_execution_data = true`, enviando logs para o CloudWatch Log Group `/aws/vendedlogs/states/tmdb-sfn-backfill-{env}`.

**Fluxo da execução:**

1. **GenerateYears** (Pass) — extrai o ano do timestamp de execução, converte para inteiro e subtrai 2 (`end_year`)
2. **ComputeYears** (Pass) — gera o array `[start_year, ..., end_year]` via `States.ArrayRange`
3. **CreateBatches** (Pass) — divide o array de anos em sub-arrays de 2 elementos via `States.ArrayPartition` (ex: `[2000,2001,2002,2003,2004]` → `[[2000,2001],[2002,2003],[2004]]`)
4. **ProcessBatches** (Map, `MaxConcurrency=1`) — itera cada batch sequencialmente:
   - **InvokeLambdaMovie** — invoca a Lambda com payload de filmes para o batch (Retry: 2 tentativas, intervalo de 30s, backoff 2.0)
   - **WaitBeforeTV** — aguarda 5 min para o Glue Details terminar antes de iniciar séries
   - **InvokeLambdaTV** — invoca a Lambda com payload de séries para o batch (Retry: 2 tentativas, intervalo de 30s, backoff 2.0)
   - **WaitBeforeNextBatch** — aguarda 5 min antes do próximo batch

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
- **Log groups** para Lambda, Glue e Step Functions com retenção configurável:
  - `dev`: 1 dia (reduz custo)
  - `prod`: 5 dias (permite investigar incidentes)
