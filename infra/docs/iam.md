# Permissões — IAM

## Roles e Policies (`iam_roles.tf`, `iam_policies.tf`)

| Role | Usada por | Permissões principais |
|---|---|---|
| `tmdb-lambda-api-{env}` | Lambda API | S3 (SOR, AUX), Glue (StartJobRun + GetJobRun — ETL e AGG), Secrets Manager |
| `tmdb-glue-etl-{env}` | Glue ETL | S3 (SOR, SOT, AUX), Glue Catalog, StartJobRun (DQ, Details) |
| `tmdb-glue-data-quality-{env}` | Glue Data Quality | S3 (SOT, SPEC, DQ), Glue Catalog, SNS (tópicos DQ direto), CloudWatch |
| `tmdb-glue-agg-{env}` | Glue AGG | S3 (SOT, SPEC, TEMP), Glue Catalog, Athena, StartJobRun (DQ) |
| `tmdb-glue-details-{env}` | Glue Details | S3 (SOT, TEMP), Glue Catalog, Athena, Secrets Manager, StartJobRun (AGG, DQ) |
| `tmdb-sfn-backfill-{env}` | Step Functions | `lambda:InvokeFunction` sobre a Lambda API, CloudWatch Logs (logging de execução) |
| `tmdb-eventbridge-sfn-{env}` | EventBridge (regra anual) | `states:StartExecution` sobre a state machine de backfill |
| `tmdb-lightsail-scheduler-{env}` | Lambda Lightsail Scheduler | `lightsail:StartInstance`, `StopInstance`, `GetInstance` |
| `tmdb-filmbot-agent-{env}` (user) | Lightsail FilmBot | Athena, S3 (SPEC, TEMP), Glue Catalog, CloudWatch Logs, Secrets Manager |

Políticas com least-privilege: cada role tem acesso apenas aos recursos que realmente precisa.

A Lambda usa uma **policy inline customizada** para logs em vez de `AWSLambdaBasicExecutionRole` (policy gerenciada da AWS). Motivo: a policy gerenciada inclui `logs:CreateLogGroup`, que permitiria à Lambda criar grupos de log sem a retenção configurada pelo Terraform. Com a policy customizada, só permitimos `CreateLogStream` e `PutLogEvents` em grupos que o `cloudwatch_logs.tf` já criou com retenção controlada.

Pelo mesmo princípio, os jobs Glue usam uma **policy compartilhada customizada** (`glue_shared_base`) em vez da managed policy `AWSGlueServiceRole`. Motivo: `AWSGlueServiceRole` concede `glue:*` em `Resource: *`, anulando todas as policies granulares de Catalog, S3 e logs definidas por job. A policy customizada fornece apenas o mínimo para o runtime Glue funcionar: `cloudwatch:PutMetricData` (métricas de job) e acesso S3 aos buckets temporários `aws-glue-*` (necessários para jobs Spark como o Data Quality).

## Permissões do CI/CD (`iam_cicd.tf`)

A role do GitHub Actions (`lsg-github-actions-{env}`) foi originalmente criada **manualmente** e depois importada (`terraform import`) para ser gerenciada como `aws_iam_role.github_actions` em `iam_cicd.tf`, que também cria e anexa 6 policies managed de privilégio mínimo. O nome da role (`cicd_role_name`) e o prefixo das policies (`cicd_policy_prefix`) vêm de `infra/config/project.json` — os valores abaixo são os defaults:

**MaxSessionDuration:** a role tem `max_session_duration = 21600` (6h) fixado no código — um teto, não uma duração forçada. O workflow `05_backfill.yml` não pede mais `role-duration-seconds` customizado (usa o default de 1h da action `aws-actions/configure-aws-credentials`): backfills históricos podem rodar por horas e a sessão expira antes do fim, e em vez de esticar a sessão o step "Executar backfill" trata `ExpiredTokenException` especificamente — reassume a role via `aws sts assume-role-with-web-identity` inline (nova sessão de 1h) e retoma o script do checkpoint em S3 (ver `scripts/backfill_checkpoint.py` e a seção `05_backfill.yml` em `estrutura-projeto.md`). O teto de 21600s na role não precisa ser reduzido — só deixa de ser usado na prática.

A policy `cicd-terraform-iam-{env}` concede à própria role permissão para se auto-gerenciar (`iam:UpdateRole`, `iam:UpdateAssumeRolePolicy`, `iam:TagRole`/`UntagRole`), sem poder se criar ou deletar (statement `IAMCICDRoleManagement`).

| Policy | Escopo |
|---|---|
| `cicd-terraform-backend-{env}` | DynamoDB (state lock) + STS (caller identity) |
| `cicd-terraform-s3-{env}` | 6 buckets do projeto + bucket de state |
| `cicd-terraform-iam-{env}` | Roles/policies/users `tmdb-*` + auto-gerenciamento `cicd-terraform-*` |
| `cicd-terraform-compute-{env}` | Lambda, Glue (jobs + catalog), Step Functions |
| `cicd-terraform-observability-{env}` | EventBridge, CloudWatch (logs + alarms — inclui log groups `/lightsail/tmdb-*`), SNS, SQS (DLQ) |
| `cicd-terraform-lightsail-{env}` | Instância, key pair, static IP em us-east-1 |

O workflow do GitHub Actions (`02_terraform.yml`) resolve o problema de bootstrap automaticamente: antes do `terraform plan`, um step aplica as 6 policies com `-target`, garantindo que a role tenha permissões antes de gerenciar os demais recursos. O step é idempotente — se as policies já existem, é um no-op.

Um recurso `terraform_data.cicd_policies_ready` sincroniza a criação: os buckets S3 e as IAM roles do projeto só são criados **depois** que as 6 policies estejam attachadas à role do GitHub Actions.
