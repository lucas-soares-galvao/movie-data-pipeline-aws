# infra — Infraestrutura AWS (Terraform)

## Visão geral

Toda a infraestrutura do projeto é gerenciada como código com **Terraform**. Isso garante que os ambientes `dev` e `prod` sejam idênticos em estrutura, reproduzíveis e auditáveis via Git. Os valores sensíveis (e-mails, ARNs, chaves) são passados via arquivos `.tfvars` por ambiente.

O estado do Terraform é armazenado remotamente em um bucket S3 com backend configurado em `provider.tf`.

Todos os recursos AWS deste projeto recebem o prefixo `tmdb-` (ou `tmdb_` para databases/tabelas do Glue Catalog), definido em `local.tmdb_prefix` (`locals.tf`). O objetivo é isolar os recursos deste projeto de outros que eventualmente compartilhem a mesma conta/região AWS.

## Ambientes

| Ambiente | Conta AWS | Arquivo de variáveis |
|---|---|---|
| `dev` | `<AWS_ACCOUNT_ID_DEV>` | `infra/envs/dev/terraform.tfvars` |
| `prod` | `<AWS_ACCOUNT_ID_PROD>` | `infra/envs/prod/terraform.tfvars` |

Cada recurso recebe o sufixo `-dev` ou `-prod` automaticamente via `locals.tf`, garantindo isolamento total entre ambientes na mesma conta (quando aplicável) ou contas separadas.

## Recursos AWS provisionados

### Armazenamento — S3 (`s3.tf`)

6 buckets com papéis distintos na arquitetura medalhão:

| Bucket | Nome (sem sufixo de ambiente) | Papel |
|---|---|---|
| SOR | `lsg-sa-east-1-bucket-sor` | Source of Record — dados brutos (JSON da TMDB) |
| SOT | `lsg-sa-east-1-bucket-sot` | Source of Truth — dados processados (Parquet) |
| SPEC | `lsg-sa-east-1-bucket-spec` | Specialized — tabela unificada para o app (Gold) |
| DQ | `lsg-sa-east-1-bucket-data-quality` | Resultados de validação de qualidade |
| AUX | `lsg-sa-east-1-bucket-aux` | Auxiliar — artefatos de código (zips, wheels) |
| TEMP | `lsg-sa-east-1-bucket-temp` | Temporário — resultados de queries Athena |

> Dentro dos buckets AUX, TEMP e SPEC, os objetos também são gravados sob um prefixo de chave `tmdb/` (scripts e wheels dos jobs Glue, resultados temporários do Athena, dados gravados pelo Glue AGG).

### Computação — Lambda (`lambda_api.tf`)

- Função Lambda `lambda-api-{env}` com timeout e memória configurados
- Pacote Python gerado por `infra/scripts/build_lambda_package.py` e enviado ao bucket AUX
- Variáveis de ambiente injetadas pelo Terraform (nomes de buckets, jobs, ARN do segredo)

### Computação — Glue Jobs (`glue_etl.tf`, `glue_details.tf`, `glue_agg.tf`, `glue_data_quality.tf`)

4 jobs Glue. Os jobs ETL, Details e AGG são do tipo **PythonShell** (Glue 3.9). O job Data Quality é do tipo **Spark (`glueetl`)** (Glue 5.0, 2 workers G.1X, execução FLEX) — exigido pela API `EvaluateDataQuality` da AWS. Cada job tem:
- Worker type e número de workers configurados por ambiente
- Wheel Python gerado por `infra/scripts/build_glue_wheel.py` e enviado ao bucket AUX
- Argumentos padrão definidos no Terraform (buckets, nomes de tabelas, databases)
- Argumentos dinâmicos injetados no momento do `start_job_run` pela Lambda/job anterior

### Catálogo — Glue Catalog (`glue_catalog.tf`)

3 databases e 16 tabelas registradas via Terraform:

| Database | Tabelas |
|---|---|
| `db_tmdb_movie_{env}` | tb_tmdb_discover_movie_{env}, tb_tmdb_genre_movie_{env}, tb_tmdb_configuration_languages_{env}, tb_tmdb_details_movie_{env}, tb_tmdb_watch_providers_movie_{env}, tb_tmdb_watch_providers_ref_movie_{env}, tb_tmdb_now_playing_movie_{env} |
| `db_tmdb_tv_{env}` | tb_tmdb_discover_tv_{env}, tb_tmdb_genre_tv_{env}, tb_tmdb_configuration_countries_{env}, tb_tmdb_details_tv_{env}, tb_tmdb_watch_providers_tv_{env}, tb_tmdb_watch_providers_ref_tv_{env} |
| `db_tmdb_unified_{env}` | tb_tmdb_data_quality_{env} |

> Antes da introdução do prefixo `tmdb`, esses nomes de database/tabela não levavam sufixo de ambiente — uma inconsistência com a seção [Ambientes](#ambientes), já corrigida: agora `db_tmdb_movie_dev` e `db_tmdb_movie_prod` (por exemplo) são databases distintas.

> `tb_tmdb_discover_unified_{env}` (tabela SPEC) não é declarada via Terraform — é registrada dinamicamente pelo job Glue AGG em runtime.

> A tabela `now_playing` não possui partição de ano — é um snapshot completo sobrescrito diariamente (`mode=overwrite`), diferente das tabelas `discover` que são particionadas por ano. Inclui os campos `theater_start_date` e `theater_end_date` com a janela de exibição reportada pela API do TMDB.

### Agendamento — EventBridge (`eventbridge.tf`)

5 regras de schedule, separadas por tipo de mídia e frequência:

| Regra | Frequência | Horário | Comportamento |
|---|---|---|---|
| `lambda_api_movie_daily` | Diária | 07:00 BRT (10:00 UTC) | `only_discover=true` — filmes novos + now_playing |
| `lambda_api_tv_daily` | Diária | 07:05 BRT (10:05 UTC) | `only_discover=true` — séries novas |
| `lambda_api_movie_monthly` | Dia 1 do mês | 07:00 BRT (10:00 UTC) | `skip_daily=true` — atualiza gêneros, idiomas, plataformas |
| `lambda_api_tv_monthly` | Dia 1 do mês | 07:05 BRT (10:05 UTC) | `skip_daily=true` — atualiza gêneros, países, plataformas |
| `sfn_backfill_annual` | 1 de jan (anual) | 07:30 BR (10:30 UTC) | Inicia o Step Function de backfill histórico com `{"start_year": 2000}` |

### Orquestração — Step Functions (`step_functions.tf`)

State machine `tmdb-sfn-backfill-{env}` para coleta histórica de dados ano a ano, contornando o limite de 15 minutos da Lambda.

**Acionamento:** regra EventBridge `sfn_backfill_annual` no dia 1º de janeiro às 10:30 UTC, com input `{"start_year": 2000}`.

**Fluxo da execução:**

1. **GenerateYears** (Pass) — extrai o ano atual do timestamp de execução e o converte para inteiro
2. **ComputeYears** (Pass) — gera o array `[start_year, ..., end_year]` via `States.ArrayRange`
3. **ProcessEachYear** (Map, `MaxConcurrency=1`) — itera cada ano sequencialmente:
   - **InvokeLambdaMovie** — invoca a Lambda com payload de filmes para o ano
   - **InvokeLambdaTV** — invoca a Lambda com payload de séries para o ano
   - Retry: 2 tentativas, intervalo de 30s, backoff 2.0

### Notificações — SNS (`sns_topics.tf`)

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

### Observabilidade — CloudWatch (`cloudwatch_alarms.tf`, `cloudwatch_glue_alarms.tf`, `cloudwatch_logs.tf`)

- **Alarmes** para cada job Glue e para a Lambda (falhas, timeouts)
- **Alarmes de métricas DQ** para o Glue Data Quality (regras com falha)
- **Log groups** para Lambda e Glue com retenção configurável:
  - `dev`: 7 dias (reduz custo)
  - `prod`: 30 dias (permite investigar incidentes)

### Servidor — Lightsail (`lightsail_ia.tf`)

- Instância `tmdb-filmbot-{env}` (`micro_3_0` — 2 vCPU, 1 GB RAM, $7/mês) para hospedar o app Streamlit
- **Caddy** como proxy reverso na porta 80
- Streamlit escuta apenas em `127.0.0.1:8501` (não acessível diretamente pela internet)
- Portas abertas: 22 (SSH — CIDR configurável via `lightsail_ssh_allowed_cidrs`), 80 (redirect HTTP→HTTPS + ACME challenge), 443 (HTTPS — proxy reverso para Streamlit)
- IP estático fixo (`tmdb-filmbot-static-ip-{env}`) para URL estável
- IAM user `tmdb-filmbot-agent-{env}` com acesso mínimo a Athena, S3 SPEC/TEMP e Glue Catalog
- Controlado pela variável `lightsail_enabled` (default `true`). Em `dev` está desabilitado (`false`) — a instância não é criada e o CI/CD ignora o deploy SSH. Para reativar: mudar para `true` em `infra/envs/dev/terraform.tfvars` e fazer push no `develop`.

**Agendamento de custo** (`lightsail_scheduler.tf`): Lambda + EventBridge com 3 regras de schedule. Desliga todos os dias às **00:00 BRT** (`cron(00 03 ? * * *)`); inicia às **18:00 BRT de seg–sex** (`cron(00 21 ? * MON-FRI *)`) e às **08:00 BRT aos sáb–dom** (`cron(00 11 ? * SAT-SUN *)`). Habilitado apenas quando `lightsail_enabled = true`.

### Permissões — IAM (`iam_roles.tf`, `iam_policies.tf`)

| Role | Usada por | Permissões principais |
|---|---|---|
| `tmdb-lambda-api-{env}` | Lambda API | S3 (SOR, AUX), Glue (StartJobRun + GetJobRun — ETL e AGG), Secrets Manager |
| `tmdb-glue-etl-{env}` | Glue ETL | S3 (SOR, SOT, AUX), Glue Catalog, StartJobRun (DQ, Details) |
| `tmdb-glue-data-quality-{env}` | Glue Data Quality | S3 (SOT, SPEC, DQ), Glue Catalog, SNS (tópicos DQ direto), CloudWatch |
| `tmdb-glue-agg-{env}` | Glue AGG | S3 (SOT, SPEC, TEMP), Glue Catalog, Athena |
| `tmdb-glue-details-{env}` | Glue Details | S3 (SOT, TEMP), Glue Catalog, Athena, Secrets Manager, StartJobRun (AGG, DQ) |
| `tmdb-sfn-backfill-{env}` | Step Functions | `lambda:InvokeFunction` sobre a Lambda API |
| `tmdb-eventbridge-sfn-{env}` | EventBridge (regra anual) | `states:StartExecution` sobre a state machine de backfill |

Políticas com least-privilege: cada role tem acesso apenas aos recursos que realmente precisa.

A Lambda usa uma **policy inline customizada** para logs em vez de `AWSLambdaBasicExecutionRole` (policy gerenciada da AWS). Motivo: a policy gerenciada inclui `logs:CreateLogGroup`, que permitiria à Lambda criar grupos de log sem a retenção configurada pelo Terraform. Com a policy customizada, só permitimos `CreateLogStream` e `PutLogEvents` em grupos que o `cloudwatch_logs.tf` já criou com retenção controlada.

## CI/CD — GitHub Actions (`.github/workflows/`)

| Arquivo | Papel |
|---|---|
| `00_pipeline.yml` | Orquestrador: chama test → terraform → PR em sequência |
| `01_test.yml` | Reusável: roda pytest, ruff (lint), mypy (tipos), bandit (segurança) |
| `02_terraform.yml` | Reusável: `terraform init` + `apply` ou `destroy` |
| `03_pr_auto.yml` | Reusável: cria PR automático após deploy |
| `04_deploy_lightsail.yml` | Deploy do app FilmBot na instância Lightsail |

Autenticação com AWS via **OIDC** (sem chaves de acesso hardcodadas) — o GitHub Actions assume uma role IAM com permissão de deploy.

## Como aplicar

### Pré-requisitos
- Terraform `>= 1.5.0` instalado (provider AWS `~> 6.0` — ver `provider.tf`)
- AWS CLI configurado com credenciais do ambiente-alvo
- Arquivo `.tfvars` preenchido para o ambiente

### Comandos

```bash
# A partir da pasta infra/
terraform init -backend-config="envs/dev/backend.hcl"
terraform plan -var-file="envs/dev/terraform.tfvars"
terraform apply -var-file="envs/dev/terraform.tfvars"
```

### Build dos artefatos de código

Antes do `terraform apply`, os artefatos Python precisam existir no bucket AUX:

```bash
python infra/scripts/build_lambda_package.py   # gera zip da Lambda
python infra/scripts/build_glue_wheel.py       # gera wheel dos jobs Glue
```

No CI/CD, o build da Lambda é automatizado pelo workflow `02_terraform.yml`. O wheel do Glue (`build_glue_wheel.py`) deve ser gerado e enviado ao bucket AUX manualmente antes do primeiro `apply` — após isso, só precisa ser regerado quando o código dos jobs Glue mudar.
