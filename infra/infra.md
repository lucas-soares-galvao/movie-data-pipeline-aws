# infra — Infraestrutura AWS (Terraform)

## Visão geral

Toda a infraestrutura do projeto é gerenciada como código com **Terraform**. Isso garante que os ambientes `dev` e `prod` sejam idênticos em estrutura, reproduzíveis e auditáveis via Git. Os valores sensíveis (e-mails, ARNs, chaves) são passados via arquivos `.tfvars` por ambiente.

O estado do Terraform é armazenado remotamente em um bucket S3 com backend configurado em `provider.tf`.

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
| `db_movie_tmdb` | discover, genre, configuration_languages, details, watch_providers, watch_providers_ref, now_playing |
| `db_tv_tmdb` | discover, genre, configuration_countries, details, watch_providers, watch_providers_ref |
| `db_unified_tmdb` | tb_data_quality_tmdb |

> `tb_discover_unified_tmdb` (tabela SPEC) não é declarada via Terraform — é registrada dinamicamente pelo job Glue AGG em runtime.

> A tabela `now_playing` não possui partição de ano — é um snapshot completo sobrescrito diariamente (`mode=overwrite`), diferente das tabelas `discover` que são particionadas por ano. Inclui os campos `theater_start_date` e `theater_end_date` com a janela de exibição reportada pela API do TMDB.

### Agendamento — EventBridge (`eventbridge_lambda_api.tf`)

4 regras de schedule, separadas por tipo de mídia:

| Regra | Frequência | Horário | Comportamento |
|---|---|---|---|
| `lambda_api_movie_daily` | Diária | 19:00 BRT (22:00 UTC) | `only_discover=true` — filmes novos + now_playing |
| `lambda_api_tv_daily` | Diária | 19:05 BRT (22:05 UTC) | `only_discover=true` — séries novas |
| `lambda_api_movie_monthly` | Dia 1 do mês | 09:00 BRT (12:00 UTC) | `skip_daily=true` — atualiza gêneros, idiomas, plataformas |
| `lambda_api_tv_monthly` | Dia 1 do mês | 09:05 BRT (12:05 UTC) | `skip_daily=true` — atualiza gêneros, países, plataformas |

### Notificações — SNS (`sns_topics.tf`)

8 tópicos SNS, um por evento relevante do pipeline. Cada tópico envia alertas para um e-mail configurado em `.tfvars`:

| Tópico | Evento |
|---|---|
| `lambda-failure-notifications` | Falha na Lambda API |
| `eventbridge-failure-notifications` | Falha no agendamento EventBridge |
| `glue-etl-failure-notifications` | Falha no job ETL |
| `glue-details-failure-notifications` | Falha no job Details |
| `glue-agg-failure-notifications` | Falha no job AGG |
| `glue-agg-success-notifications` | Sucesso do job AGG |
| `glue-data-quality-failure-notifications` | Falha nas regras de DQ |
| `glue-data-quality-metrics-notifications` | Métricas de DQ (resultados das regras) |

### Observabilidade — CloudWatch (`cloudwatch_alarms.tf`, `cloudwatch_glue_alarms.tf`, `cloudwatch_logs.tf`)

- **Alarmes** para cada job Glue e para a Lambda (falhas, timeouts)
- **Alarmes de métricas DQ** para o Glue Data Quality (regras com falha)
- **Log groups** para Lambda e Glue com retenção configurável:
  - `dev`: 7 dias (reduz custo)
  - `prod`: 30 dias (permite investigar incidentes)

### Servidor — Lightsail (`lightsail_ia.tf`)

- Instância `filmbot-{env}` (`micro_3_0` — 2 vCPU, 1 GB RAM, $7/mês) para hospedar o app Streamlit
- Portas abertas: 22 (SSH — CIDR configurável via `lightsail_ssh_allowed_cidrs`), 80 (HTTP), 443 (HTTPS) e 8501 (Streamlit)
- IP estático fixo (`filmbot-static-ip-{env}`) para URL estável
- IAM user `filmbot-agent-{env}` com acesso mínimo a Athena, S3 SPEC/TEMP e Glue Catalog
- Controlado pela variável `lightsail_enabled` (default `true`). Em `dev` está desabilitado (`false`) — a instância não é criada e o CI/CD ignora o deploy SSH. Para reativar: mudar para `true` em `infra/envs/dev/terraform.tfvars` e fazer push no `develop`.

**Agendamento de custo** (`lightsail_scheduler.tf`): Lambda + EventBridge que liga a instância às **08:00 BRT** (`cron(00 11 * * ? *)`) e desliga às **23:00 BRT** (`cron(00 02 * * ? *)`), economizando ~37% do custo mensal. Habilitado apenas quando `lightsail_enabled = true`.

### Permissões — IAM (`iam_roles.tf`, `iam_policies.tf`)

| Role | Usada por | Permissões principais |
|---|---|---|
| `lambda-role` | Lambda API | S3 (SOR), Glue (start_job_run), Secrets Manager |
| `glue-job-role-etl-{env}` | Glue ETL | S3 (todos os buckets), Glue Catalog, Athena, SNS, CloudWatch |
| `glue-job-role-etl-dq` | Glue Data Quality | S3 (SOR, SOT, DQ), Glue Catalog, SNS, CloudWatch |
| `glue-job-role-etl-agg` | Glue AGG | S3 (SOT, SPEC, TEMP), Glue Catalog, Athena, SNS, CloudWatch |
| `glue-job-role-etl-details` | Glue Details | S3 (SOR, SOT), Glue Catalog, SNS, CloudWatch |

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
