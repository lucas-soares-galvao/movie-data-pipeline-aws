# Pipeline e Observabilidade

## Agendamento — EventBridge (`eventbridge.tf`)

9 regras de schedule, separadas por tipo de mídia e frequência. Os horários são espaçados com gap de 30 min entre semanal e mensal para evitar `ConcurrentModificationException` no Glue Catalog quando dois jobs Details tocam a mesma partição:

| Regra | Frequência | Horário | Comportamento |
|---|---|---|---|
| `lambda_api_movie_rotation_weekly` | Semanal (sáb) | 06:00 BRT (09:00 UTC) | `only_rotation_refresh=true` — refresh forçado de 1 ano do catálogo antigo (filmes), ponteiro via SSM |
| `lambda_api_tv_rotation_weekly` | Semanal (sáb) | 06:05 BRT (09:05 UTC) | `only_rotation_refresh=true` — refresh forçado de 1 ano do catálogo antigo (séries), ponteiro via SSM |
| `lambda_api_movie_weekly` | Semanal (sáb) | 06:30 BRT (09:30 UTC) | `only_weekly_tables=true` — filmes novos + now_playing |
| `lambda_api_tv_weekly` | Semanal (sáb) | 06:35 BRT (09:35 UTC) | `only_weekly_tables=true` — séries novas |
| `lambda_api_movie_changes_weekly` | Semanal (dom) | 06:00 BRT (09:00 UTC) | `only_changes_tables=true` — refresh de filmes já catalogados (Changes API), qualquer ano |
| `lambda_api_tv_changes_weekly` | Semanal (dom) | 06:05 BRT (09:05 UTC) | `only_changes_tables=true` — refresh de séries já catalogadas (Changes API), qualquer ano |
| `lambda_api_movie_monthly` | Dia 1 do mês | 06:30 BRT (09:30 UTC) | `only_monthly_tables=true` — referências + discover do ano anterior |
| `lambda_api_tv_monthly` | Dia 1 do mês | 06:35 BRT (09:35 UTC) | `only_monthly_tables=true` — referências + discover do ano anterior |

**Sábado** roda rotation refresh (09:00/09:05) seguido do discover semanal (09:30/09:35, 30 min depois) — mesmo gap já usado entre semanal e mensal, que evita `ConcurrentModificationException` no Glue Catalog quando dois jobs Details tocam a mesma tabela; rotation e discover nunca colidem de partição (catálogo antigo vs. ano corrente), então o gap é só uma precaução, mesma lógica do par semanal/mensal. **Domingo** roda só o changes, um dia inteiro depois do discover — isolado, sem nenhum outro job Glue Details no mesmo dia, o que elimina de vez o risco de colisão de partição (changes pode tocar o ano corrente, a mesma partição que o discover escreve) e ainda garante que o catálogo já esteja atualizado com os títulos novos da semana antes do changes rodar. Diferente do modo semanal/mensal (que só cobrem o ano atual e o anterior), o modo changes usa `/movie/changes`/`/tv/changes` do TMDB para detectar títulos alterados em **qualquer** ano de lançamento — fecha o gap de staleness em todo o catálogo histórico sem re-rodar `/discover`. Ver `app/lambda_api/lambda_api.md` e `app/glue_details/glue_details.md` ("Modo changes").

**Rotation refresh** cobre o gap que o changes não fecha sozinho no catálogo antigo (o `/changes` da TMDB nem sempre reporta toda alteração real): força (`FORCE_REFETCH=true`) o refresh de 1 ano do catálogo (2000 até `current_year - 3`) por semana, via um ponteiro simples em SSM Parameter Store (`infra/ssm.tf`) que dispensa checkpoint de loop e se ajusta sozinho ano a ano. O ano corrente e o anterior não têm um modo forçado equivalente — já são refeitos naturalmente, ~mensalmente, pelo cascade do discover semanal/mensal → Glue ETL → Glue Details (sem `FORCE_REFETCH`, mas a lógica de delta do Glue Details já refaz qualquer ID não tocado no mês calendário corrente); um refresh forçado ali seria redundante com esse mecanismo gratuito. Ver `app/lambda_api/lambda_api.md` ("Modo rotation refresh").

**Dead Letter Queue (DLQ):** todos os targets do EventBridge (pipeline e Lightsail scheduler) enviam eventos não entregues para a fila SQS `tmdb-eventbridge-dlq-{env}` (`sqs.tf`), com retenção de 14 dias. Um alarme CloudWatch monitora a fila e notifica via SNS (tópico de falha do EventBridge) quando há mensagens.

## Disparo do Lightsail Scheduler via AWS (`lightsail_scheduler_trigger.tf`)

`05_lightsail_scheduler.yml` (liga/desliga o FilmBot diariamente) não usa mais o trigger `schedule:` nativo do
GitHub Actions — a documentação do GitHub descreve esse trigger como sujeito a atraso em períodos de alta carga
(especialmente no início de cada hora, exatamente o horário dos crons antigos). Duas `aws_cloudwatch_event_rule`
(só em prod, `local.lightsail_prod_enabled`) chamam a API REST do GitHub (`workflow_dispatch`) via uma EventBridge
**API Destination**, reaproveitando o input `action: start|stop` que o workflow já aceita:

| Regra | Horário | Ação |
|---|---|---|
| `lightsail_scheduler_stop` | 00:00 BRT (03:00 UTC) | `action=stop` |
| `lightsail_scheduler_start` | 08:00 BRT (11:00 UTC) | `action=start` |

A autenticação na API do GitHub usa um `aws_cloudwatch_event_connection` (`API_KEY`, header `Authorization: Bearer
<token>`) apontando para um fine-grained PAT do GitHub (permissão "Actions: Read and write", escopado só a este
repositório) — o token chega via `-var="github_workflow_dispatch_token=..."` (secret `AWS_GH_WORKFLOW_DISPATCH_TOKEN_{DEV,PROD}`,
mesmo mecanismo de `filmbot_secret_arn`, nunca em `terraform.tfvars`). A role de execução usada pelo target
(`lightsail_scheduler_eventbridge`) só tem `events:InvokeApiDestination`, escopada ao ARN da própria API
Destination. Mesmos targets têm `dead_letter_config` apontando para a DLQ compartilhada (ver acima).

## Backfill histórico manual (`06_backfill.yml`)

O backfill histórico é sempre manual: via workflow `06_backfill.yml` (GitHub Actions, `workflow_dispatch`), que dispara scripts Python diretamente contra a Lambda API e os jobs Glue Details/Data Quality — usado para correções pontuais em um grupo específico de tabelas. O ambiente (dev/prod) é resolvido automaticamente pelo branch selecionado ao disparar o workflow (ver `overview.md`).

## Notificações — SNS (`sns_topics.tf`)

8 tópicos SNS, um por evento relevante do pipeline. Cada tópico envia alertas para um e-mail configurado em `.tfvars`:

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

> Antes desta mudança, os tópicos SNS eram globais (sem sufixo de ambiente) — se dev e prod estivessem na mesma conta AWS, dividiriam o mesmo tópico/inscrição de e-mail. Agora cada ambiente tem seus próprios tópicos.

## Observabilidade — CloudWatch (`cloudwatch_alarms.tf`, `cloudwatch_glue_alarms.tf`, `cloudwatch_logs.tf`)

- **Alarmes** para cada job Glue e para a Lambda (falhas, timeouts)
- **Alarmes de métricas DQ** para o Glue Data Quality (regras com falha)
- **Log groups** para Lambda, Glue e Lightsail (FilmBot) com retenção configurável:
  - `dev`: 1 dia (reduz custo)
  - `prod`: 5 dias (permite investigar incidentes)
