# Pipeline e Observabilidade

## Agendamento — EventBridge (`eventbridge.tf`)

12 regras de schedule, separadas por tipo de mídia e frequência. Os horários são espaçados (1 h entre changes e rotation no domingo; 30 min entre mensal e ano futuro na 1ª segunda) para evitar `ConcurrentModificationException` no Glue Catalog quando dois jobs Details tocam a mesma partição:

| Regra | Frequência | Horário | Comportamento |
|---|---|---|---|
| `lambda_api_movie_rotation_weekly` | Semanal (dom) | 07:00 BRT (10:00 UTC) | `only_rotation_refresh=true` — refresh forçado de 1 ano do catálogo antigo (filmes), ponteiro via SSM |
| `lambda_api_tv_rotation_weekly` | Semanal (dom) | 07:05 BRT (10:05 UTC) | `only_rotation_refresh=true` — refresh forçado de 1 ano do catálogo antigo (séries), ponteiro via SSM |
| `lambda_api_movie_weekly` | Semanal (sáb) | 06:30 BRT (09:30 UTC) | `only_weekly_tables=true` — filmes novos + now_playing |
| `lambda_api_tv_weekly` | Semanal (sáb) | 06:35 BRT (09:35 UTC) | `only_weekly_tables=true` — séries novas |
| `lambda_api_movie_changes_weekly` | Semanal (dom) | 06:00 BRT (09:00 UTC) | `only_changes_tables=true` — refresh de filmes já catalogados (Changes API), qualquer ano |
| `lambda_api_tv_changes_weekly` | Semanal (dom) | 06:05 BRT (09:05 UTC) | `only_changes_tables=true` — refresh de séries já catalogadas (Changes API), qualquer ano |
| `lambda_api_movie_monthly` | Mensal (1ª segunda) | 06:30 BRT (09:30 UTC) | `only_monthly_tables=true` — referências + discover do ano anterior |
| `lambda_api_tv_monthly` | Mensal (1ª segunda) | 06:35 BRT (09:35 UTC) | `only_monthly_tables=true` — referências + discover do ano anterior |
| `lambda_api_movie_future_monthly` | Mensal (1ª segunda) | 07:00 BRT (10:00 UTC) | `only_future_year_tables=true` — discover do `current_year + 1` (filmes), sem referências e sem now_playing |
| `lambda_api_tv_future_monthly` | Mensal (1ª segunda) | 07:05 BRT (10:05 UTC) | `only_future_year_tables=true` — discover do `current_year + 1` (séries), sem referências |

O mensal e o ano futuro rodam na **primeira segunda-feira do mês** (`cron(... ? * 2#1 *)`), e não num dia fixo do mês: o "dia 1" caía em sábado (mesmo minuto do discover semanal, estourando `max_concurrent_runs` do ETL/Details) ou domingo (sobrepondo o Details do changes na mesma tabela) alguns meses por ano. Segunda não tem nenhum outro gatilho do pipeline.

**Sábado** roda só o discover semanal (09:30/09:35 UTC, ano corrente). **Domingo** roda o changes (09:00/09:05 UTC) e, 1 h depois, o rotation refresh (10:00/10:05 UTC). O rotation foi movido do sábado para o domingo para dividir a carga: no sábado o Glue Details chegava a 4 runs simultâneos (rotation ×2 + discover ×2), exatamente o `max_concurrent_runs`, sem folga; agora sábado tem no máximo 2 e domingo 2 por vez. O changes roda um dia inteiro depois do discover, o que elimina o risco de colisão de partição (changes pode tocar o ano corrente, a mesma partição que o discover escreve) e garante que o catálogo já tenha os títulos novos da semana. O gap de 1 h entre changes e rotation existe porque o changes pode tocar **qualquer** ano, inclusive o que o rotation está refrescando; o Details tem timeout de 30 min, então o changes termina no máximo ~09:35 UTC, antes do rotation. O rotation termina antes do Glue AGG (11:00 UTC), com margem de pior caso estimada em ~28 min (não medida). Diferente do modo semanal/mensal (que só cobrem o ano atual e o anterior), o modo changes usa `/movie/changes`/`/tv/changes` do TMDB para detectar títulos alterados em **qualquer** ano de lançamento — fecha o gap de staleness em todo o catálogo histórico sem re-rodar `/discover`. Ver `app/lambda_api/lambda_api.md` e `app/glue_details/glue_details.md` ("Modo changes").

**Rotation refresh** cobre o gap que o changes não fecha sozinho no catálogo antigo (o `/changes` da TMDB nem sempre reporta toda alteração real, e o catálogo antigo não passa mais pelo cascade normal do discover): força o refresh de 1 ano do catálogo (2000 até `current_year - 3`) por semana, via um ponteiro simples em SSM Parameter Store (`infra/ssm.tf`) que dispensa checkpoint de loop e se ajusta sozinho ano a ano. O ano corrente e o anterior não têm um modo dedicado equivalente — já são refeitos naturalmente pelo cascade do discover semanal/mensal → Glue ETL → Glue Details, que busca/atualiza todos os IDs do discover em toda execução (sem delta); um modo dedicado ali seria redundante com esse cascade. Ver `app/lambda_api/lambda_api.md` ("Modo rotation refresh").

**Dead Letter Queue (DLQ):** todos os targets do EventBridge (pipeline e Lightsail scheduler) enviam eventos não entregues para a fila SQS `tmdb-eventbridge-dlq-{env}` (`sqs.tf`), com retenção de 14 dias. Um alarme CloudWatch monitora a fila e notifica via SNS (tópico de falha do EventBridge) quando há mensagens.

## Disparo do Lightsail Scheduler via AWS (`lightsail_scheduler_trigger.tf`)

`lightsail_scheduler.yml` (liga o FilmBot só nos fins de semana e desliga todo dia) não usa mais o trigger `schedule:` nativo do
GitHub Actions — a documentação do GitHub descreve esse trigger como sujeito a atraso em períodos de alta carga
(especialmente no início de cada hora, exatamente o horário dos crons antigos). Duas `aws_cloudwatch_event_rule`
(só em prod, `local.lightsail_prod_enabled`) chamam a API REST do GitHub (`workflow_dispatch`) via uma EventBridge
**API Destination**, reaproveitando o input `action: start|stop` que o workflow já aceita:

| Regra | Horário | Ação |
|---|---|---|
| `lightsail_scheduler_stop` | 00:00 BRT (03:00 UTC), todos os dias — `cron(0 3 * * ? *)` | `action=stop` |
| `lightsail_scheduler_start` | 08:00 BRT (11:00 UTC), só sábado e domingo — `cron(0 11 ? * SAT,SUN *)` | `action=start` |

O FilmBot só é usado nos fins de semana, então a instância existe de sábado 08:00 a segunda 00:00 BRT (liga sáb e dom
às 08:00, desliga dom e seg à 00:00). O desligar continua **diário** de propósito: de segunda a sexta é no-op
(`terraform destroy -target` em recurso já destruído passa sem erro), mas derruba a instância na próxima meia-noite se um
push em `main` na semana a recriou (o `terraform apply` completo recria a instância destruída).

A autenticação na API do GitHub usa um `aws_cloudwatch_event_connection` (`API_KEY`, header `Authorization: Bearer
<token>`) apontando para um fine-grained PAT do GitHub (permissão "Actions: Read and write", escopado só a este
repositório) — o token chega via `-var="github_workflow_dispatch_token=..."` (secret `AWS_GH_WORKFLOW_DISPATCH_TOKEN_{DEV,PROD}`,
mesmo mecanismo de `filmbot_secret_arn`, nunca em `terraform.tfvars`). A role de execução usada pelo target
(`lightsail_scheduler_eventbridge`) só tem `events:InvokeApiDestination`, escopada ao ARN da própria API
Destination. Mesmos targets têm `dead_letter_config` apontando para a DLQ compartilhada (ver acima).

## Backfill histórico manual (`backfill.yml`)

O backfill histórico é sempre manual: via workflow `backfill.yml` (GitHub Actions, `workflow_dispatch`), que dispara scripts Python diretamente contra a Lambda API e os jobs Glue Details/Data Quality — usado para correções pontuais em um grupo específico de tabelas. O ambiente (dev/prod) é resolvido automaticamente pelo branch selecionado ao disparar o workflow (ver `overview.md`).

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
