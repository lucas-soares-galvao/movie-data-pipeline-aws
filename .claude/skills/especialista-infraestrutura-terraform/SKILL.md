---
name: especialista-infraestrutura-terraform
description: Especialista em infraestrutura Terraform de infra/, organizado por serviço AWS (S3, Lambda, Glue, Lightsail, IAM, EventBridge, SNS, SQS, CloudWatch, SSM). Use ao criar/alterar recursos .tf, revisar argumentos de Glue Job/Lambda/Lightsail, ajustar políticas IAM, entender depends_on entre recursos, ou seguir o padrão de nomeação via local.envs/project.json. Cobre diferenças dev/prod e o pipeline de build (wheel/zip) dos jobs Glue e da Lambda.
---

# Especialista em Infraestrutura — `infra/` por Serviço AWS

## Papel

Você é o especialista responsável pela infraestrutura Terraform em `infra/` (layout flat: um `.tf` por responsabilidade, sem `modules/`). Nomeia todo recurso via `local.envs.*` — nunca reconstrói `"${local.tmdb_prefix}-xxx-${var.env}"` inline quando já existe uma chave em `locals.tf`. Respeita a cadeia de `depends_on` existente (boa parte dos recursos depende de `terraform_data.cicd_policies_ready`). Mantém a política de menor privilégio: o projeto substitui deliberadamente managed policies amplas (`AWSGlueServiceRole`, `AWSLambdaBasicExecutionRole`) por policies customizadas em `iam_policies.tf` — não reintroduza as managed policies para "simplificar".

## Fontes de verdade (ler antes de agir)

Esta skill cobre o nível de detalhe que falta nos documentos abaixo (argumentos reais de recurso, convenções de nomeação, `depends_on`, pipeline de build); não os duplica:

| O quê | Onde |
|---|---|
| Estrutura de diretórios de `infra/`, lista de arquivos `.tf`, workflows CI/CD | `estrutura-projeto` |
| Inventário de recursos por serviço (tabelas resumidas) | `infra/docs/recursos.md` |
| Schedules EventBridge, tópicos SNS, alarmes CloudWatch | `infra/docs/pipeline.md` |
| Roles/policies IAM e racional de cada uma | `infra/docs/iam.md` |
| Convenções de deploy/ambientes/CI-CD, comandos `terraform` | `infra/docs/overview.md` |
| Código Python/SQL que essa infra hospeda | `especialista-engenharia-dados-app` |

## Convenções transversais (valem para todo `infra/*.tf`)

- `local.project_config = jsondecode(file("config/project.json"))` — fonte única de `tmdb_prefix`, nome do wheel compartilhado (`shared_wheel_name`), nome/prefixo da role de CI/CD. **Só `locals.tf` lê esse arquivo**; mudar `project.json` propaga nome para quase todo `infra/*.tf` via `local.tmdb_prefix`.
- `local.envs` — mapa único com todos os nomes sufixados por ambiente: jobs Glue (`glue_etl_job_name`, `glue_agg_job_name`, `glue_details_job_name`, `glue_data_quality_job_name`), `lambda_api_name`, roles (`iam_role_glue`, `iam_role_lambda`), os 6 buckets S3 (`s3_bucket_aux/temp/sor/sot/spec/data_quality`), 3 databases + 14 tabelas do Glue Catalog (`glue_catalog_db_*`, `glue_catalog_tb_*`) e `lightsail_instance_name`. Toda referência a nome de recurso passa por `local.envs.<chave>`, nunca é reconstruída inline.
- `local.component_tags.<componente>` — tags aplicadas por componente (`shared`, `lambda_api`, `eventbridge`, `glue_etl`, `glue_data_quality`, `glue_agg`, `glue_details`, `glue_catalog`, `lightsail_ia`); `local.default_resource_tags` (Service/Environment/FinOps) vai no `default_tags` do provider.
- Único padrão de repetição no projeto é `count = var.lightsail_enabled ? 1 : 0` — não há `for_each` em lugar nenhum de `infra/`.
- `depends_on` explícito é comum porque o Terraform não infere ordem a partir de interpolação de string dentro de `default_arguments`/`environment` (argumentos de Glue Job/Lambda são strings, não referências diretas).
- Dois providers: default (`sa-east-1`, com `default_tags`) e `aws.lightsail` (`us-east-1` — obrigatório, a API do Lightsail só responde nessa região).
- `local.eventbridge_schedule_state` — `"ENABLED"` só em prod, `"DISABLED"` em dev (evita custo/consumo de API TMDB em dev).

## Organização por serviço AWS

### Amazon S3 — `s3.tf`

6 buckets, todos com o mesmo padrão de 4 recursos: `aws_s3_bucket` + `aws_s3_bucket_public_access_block` (todas as 4 flags `true`) + `aws_s3_bucket_server_side_encryption_configuration` (SSE-S3/AES256) + `aws_s3_bucket_lifecycle_configuration` + `aws_s3_bucket_policy` (nega requests sem `aws:SecureTransport`). Todos com `force_destroy = true` e `depends_on = [terraform_data.cicd_policies_ready]`.

| Bucket (`local.envs.*`) | Papel | Lifecycle |
|---|---|---|
| `s3_bucket_aux` | Código/artefatos (wheels, zips) | Transição IA em 30d |
| `s3_bucket_temp` | Scratch do Athena (glue_agg) | **Expira em 1 dia** — sem transição IA |
| `s3_bucket_sor` | JSON bruto (lambda_api) | Transição IA em 30d |
| `s3_bucket_sot` | Parquet processado (glue_etl) | Transição IA em **90d** |
| `s3_bucket_spec` | Tabela unificada (glue_agg) | Transição IA em **90d** |
| `s3_bucket_data_quality` | Resultados de DQ | Transição IA em 30d |

Ao criar um bucket novo: seguir o mesmo bloco de 5 recursos, adicionar a chave em `local.envs`, e escolher lifecycle conforme o padrão de acesso (dados efêmeros → expiração curta sem IA, como TEMP; dados de longo prazo consultados raramente → IA em 30-90d).

### AWS Lambda — `lambda_api.tf`

- **`lambda_api`** (`aws_lambda_function.simple_lambda`) — `runtime="python3.11"`, `architecture="arm64"`, `timeout=900s`, `memory_size=512MB`, handler `main.lambda_handler`. Deploy **via S3** (não código inline): `null_resource.lambda_build` (local-exec rodando `scripts/build_lambda_package.py`, `triggers` = sha256 do código-fonte + shared_src + requirements + o próprio script builder) → `data.archive_file.lambda_bundle` (zip) → upload no bucket AUX → `s3_bucket`/`s3_key` na function. Cadeia longa de `depends_on` (policies IAM, log group, objeto S3, build).

### AWS Glue — jobs PythonShell — `glue_etl.tf`, `glue_agg.tf`, `glue_details.tf`

Os três compartilham o mesmo esqueleto: `command.name="pythonshell"`, `command.python_version="3.9"`, `max_capacity=local.pythonshell_min_capacity` (0.0625 DPU), `max_retries=0`, `job_run_queuing_enabled=true`, `notification_property.notify_delay_after=3` min. Deploy como **`.whl`** via `--extra-py-files` (PythonShell não suporta `.zip`) — código do próprio job **e** o wheel `tmdb_shared`. `--additional-python-modules` vem de `local.<job>_additional_python_modules`, montado por list-comprehension a partir do `requirements.txt` do job (ver `locals.tf`).

| Job | Timeout | `max_concurrent_runs` | Observação |
|---|---|---|---|
| `glue_etl_job_name` (ETL) | 15min | 7 | SOR→SOT; dispara DQ e Details ao concluir |
| `glue_agg_job_name` (AGG) | 30min | 1 | Unifica movie+tv via SQL Athena; dispara DQ; próprio `aws_glue_trigger` SCHEDULED (sáb/dom 08:00 BRT), não é mais acionado pelo Details |
| `glue_details_job_name` (Details) | 30min | 4 | Enriquece runtime/temporadas/streaming; dispara DQ |

### AWS Glue — job Spark — `glue_data_quality.tf`

`data_quality_job` — `glue_version="5.0"`, `command.name="glueetl"` (**Spark**, não PythonShell — exigido pelo SDK `EvaluateDataQuality`), `number_of_workers=2`, `worker_type="G.1X"`, `execution_class="FLEX"`, timeout 30min, `max_concurrent_runs=15` (pior caso: 13 execuções semanais + sobreposição mensal/anual). Deploy como **`.zip`** (não wheel — jobs Spark suportam zip). Publica métricas direto no SNS via argumento `SNS_TOPIC_ARN_DQ_METRICS`.

**Nunca trocar o formato de deploy entre os dois tipos de job**: PythonShell → `.whl`; Spark (glue_data_quality) → `.zip`.

### AWS Glue Catalog — `glue_catalog.tf` (~1155 linhas)

3 `aws_glue_catalog_database` (`glue_catalog_db_movie/tv/unified`) + 14 `aws_glue_catalog_table` (todas `EXTERNAL_TABLE`, Parquet, Hive SerDe), a maioria com `partition_keys { name = "year" }` (exceções: `now_playing`, `watch_providers_ref_movie/tv` — sem partição por ano; a tabela de DQ particiona por `source_table` + `year`). Cada tabela declara `storage_descriptor.columns` explicitamente e aponta para `s3://<bucket>/tmdb/<table_name>/`.

**Importante**: a tabela SPEC (`glue_catalog_tb_discover_unified`, `tb_tmdb_discover_unified_{env}`) **não está declarada aqui** — é registrada em runtime pelo próprio job Glue AGG (`wr.s3.to_parquet(..., database=..., table=...)`). Não adicione essa tabela ao `glue_catalog.tf`; isso duplicaria a definição e causaria drift.

### Amazon Lightsail — `lightsail_ia.tf`

`aws_lightsail_instance.filmbot` (gated por `var.lightsail_enabled`) — `bundle_id=var.lightsail_bundle_id` (`micro_3_0` em prod, `nano_3_0` mais barato em dev), `blueprint_id="ubuntu_22_04"`, AZ `us-east-1a`, `provider = aws.lightsail`. Acompanhado de key pair, IP estático + attachment, portas públicas (22 restrita a `var.lightsail_ssh_allowed_cidrs`; 80/443 abertas a `0.0.0.0/0`).

Os 4 outputs que indexam `recurso[0]` (`lightsail_public_ip`, `lightsail_url`, `lightsail_private_key`, `lightsail_instance_name`) usam guarda `length(recurso) > 0 ? recurso[0].attr : ""`, não `var.lightsail_enabled ? ... : ""` — necessário porque o scheduler (`05_lightsail_scheduler.yml`) destrói/recria `aws_lightsail_instance.filmbot` via `-target` enquanto `lightsail_enabled` permanece `true`; com a guarda antiga, `terraform destroy -target=aws_lightsail_instance.filmbot` quebraria ao recalcular os outputs no final (índice inválido numa lista vazia).

Usa `aws_iam_user.lightsail_agent` (**usuário, não role** — a instância Lightsail não assume roles IAM) com access key gerenciada pelo Terraform (output sensível), policy escopada para Athena, S3 (SPEC leitura, TEMP leitura/escrita), Glue read, CloudWatch Logs, Secrets Manager. Vários `output` (IP, URL, private key, access keys, log group, path de saída do Athena, DB/tabela do Glue) alimentam o `.env` da instância — consumidos pelo workflow `04_deploy_lightsail.yml`, não fixados no Terraform.

### IAM — `iam_roles.tf`, `iam_policies.tf`, `iam_cicd.tf`, `iam_backfill.tf`

- **`iam_roles.tf`** — roles de serviço (`lambda_function`, `glue_etl_role`, `glue_dq_role`, `glue_agg_role`, `glue_details_role`), todas com `assume_role_policy` de service principal, anexadas às duas managed policies **customizadas** compartilhadas (`glue_shared_base`, `glue_shared_read_code`) definidas em `iam_policies.tf`. Todas dependem de `terraform_data.cicd_policies_ready`.
- **`iam_policies.tf`** (~1024 linhas) — policies por job (logs, S3 escopado por prefixo, Glue Catalog escopado por ARN de DB/tabela, Athena, Secrets Manager, SSM, Translate/Comprehend para fallback de tradução) + `aws_sns_topic_policy` (via `aws_iam_policy_document`) controlando quem publica em cada tópico SNS. `glue_shared_base` substitui `AWSGlueServiceRole` (concede `glue:*` em `*` — permissiva demais); a policy de logs da Lambda substitui `AWSLambdaBasicExecutionRole` (permitiria `logs:CreateLogGroup`, ignorando a retenção gerenciada pelo Terraform).
- **`iam_cicd.tf`** — `aws_iam_role.github_actions` (`lsg-github-actions-{env}`, trust OIDC, `max_session_duration=3600`) + 8 policies least-privilege (backend/state-lock, S3, IAM self-mgmt escopado a `tmdb-*`, compute, observability, lightsail, ssm, route53). Termina em `terraform_data.cicd_policies_ready` — **quase todo outro recurso do projeto depende dela** — seguida de `null_resource.cicd_policies_propagation` que faz polling em `iam:SimulatePrincipalPolicy` (até 60s) contornando a consistência eventual do IAM.
- **`iam_backfill.tf`** — role separada `tmdb-backfill-role-{env}` para o workflow manual `06_backfill.yml` (antes reusava a role de CI/CD — excesso de privilégio). Trust policy restrita por repo **e** branch (`local.backfill_allowed_branch`: dev→`develop`, prod→`main`). Policies escopadas: invocar Lambda, iniciar/monitorar Glue Details+DQ, S3 (checkpoints + prefixos específicos da SOT), Glue Catalog (só tabelas de details/watch_providers).

Ao adicionar permissão nova: sempre uma policy customizada com escopo mínimo — nunca anexar uma managed policy ampla como atalho.

### Amazon EventBridge — `eventbridge.tf`

9 `aws_cloudwatch_event_rule` (cron) disparando `aws_lambda_function.simple_lambda`, todas com `state = local.eventbridge_schedule_state` (habilitado só em prod) e payload `input` montado a partir de `local.envs.*`:
- Rotation refresh semanal (sáb 06:00/06:05 BRT)
- Discover semanal (sáb 06:30/06:35 BRT) — `only_weekly_tables=true`
- Changes semanal (dom 06:00/06:05 BRT) — `only_changes_tables=true`
- Mensal (dia 1, 06:30/06:35 BRT) — `only_monthly_tables=true`

Horários escalonados em 5-30min de intervalo deliberadamente, para evitar `ConcurrentModificationException` no Glue Catalog quando múltiplas execuções tocam a mesma tabela. Cada target tem `dead_letter_config` apontando para o SQS DLQ e um `aws_lambda_permission` para o principal `events.amazonaws.com`.

### Amazon SNS — `sns_topics.tf`

8 tópicos (um por evento do pipeline: falha DQ, métricas DQ, falha ETL, falha Lambda, falha EventBridge, sucesso AGG, falha AGG, falha Details), cada um com `aws_sns_topic_subscription` (protocolo `email`, endereço vindo de uma variável dedicada por tópico, ex. `var.glue_etl_notification_email`). Nome de exibição usa prefixo `[${upper(var.env)}] ...`. **Quem pode publicar** em cada tópico é definido em `iam_policies.tf` (`aws_sns_topic_policy`), não aqui.

### Amazon SQS — `sqs.tf`

Fila única `aws_sqs_queue.eventbridge_dlq`, retenção 14 dias (1209600s), com policy permitindo `events.amazonaws.com` fazer `SendMessage`, escopada por `aws:SourceArn` às regras `arn:aws:events:...:rule/${tmdb_prefix}-*`.

### AWS SSM Parameter Store — `ssm.tf`

2 `aws_ssm_parameter` (String) para ponteiro de rotação de coleta (`/tmdb-pipeline/rotation-year-pointer-movie|tv`), valor inicial `"1999"`, com `lifecycle { ignore_changes = [value] }` — o Terraform nunca deve reverter o progresso runtime que a Lambda escreve nesses parâmetros. Sem sufixo de ambiente no nome (contas AWS separadas por ambiente evitam colisão).

### Amazon CloudWatch — `cloudwatch_alarms.tf`, `cloudwatch_glue_alarms.tf`, `cloudwatch_logs.tf`

- **Logs**: 9 `aws_cloudwatch_log_group` (pares erro/saída dos jobs Glue, Lambda, Lightsail), todos com `retention_in_days = var.log_retention_days` (dev=1; prod maior, definido em `envs/prod/terraform.tfvars`).
- **Alarmes**: `lambda_error_alarm` (`Errors > 0`), `eventbridge_failed_alarm` (multi-metric-query somando `FailedInvocations` das 4 regras), `eventbridge_dlq_alarm` (SQS `ApproximateNumberOfMessagesVisible > 0`).
- **Notificadores por state change**: regras `aws_cloudwatch_event_rule` casando `CloudWatch Alarm State Change` (alarmes Lambda/EventBridge) e `Glue Job State Change` (ETL/DQ/AGG falha, AGG sucesso, Details falha) → `aws_cloudwatch_event_target` com `input_transformer` usando os templates heredoc `local.*_input_template` (`locals.tf`) → publica direto no tópico SNS correspondente, **sem Lambda no meio**.

### Build de código compartilhado — `shared_src.tf`

Constrói o wheel `tmdb_shared` (`null_resource` + `scripts/build_glue_wheel.py`) consumido pelos 3 jobs PythonShell, e o `.zip` equivalente consumido pelo job Spark de DQ — ambos enviados ao bucket AUX.

## Diferenças dev vs. prod

`var.env` (`dev`/`prod`, **contas AWS separadas** via AWS Organizations) controla, direta ou indiretamente: `var.lightsail_enabled`, `var.log_retention_days`, `local.eventbridge_schedule_state` (schedules só ativos em prod), `var.filmbot_secret_arn` e todos os e-mails de notificação por tópico — todos vêm de `envs/{dev,prod}/terraform.tfvars`. `cicd_statefile_s3_bucket`/`cicd_lock_dynamodb_table` **não** ficam em tfvars — chegam via `-var` a partir de secrets do GitHub Actions no workflow `02_terraform.yml`.

## Regras ao mexer em `infra/`

- Nomear recursos sempre via `local.envs.*` — se o nome não existir ainda, adicionar a chave em `locals.tf`, nunca reconstruir inline
- Recurso novo que dependa de policy/role de CI/CD: `depends_on = [terraform_data.cicd_policies_ready]`, seguindo o padrão já usado em S3/IAM
- Ao conceder permissão a uma role/job, escrever uma policy customizada com escopo mínimo — não anexar managed policy ampla
- Job Glue PythonShell → build/deploy como `.whl`; job Glue Spark (`glue_data_quality`) → `.zip` — nunca inverter
- Não declarar a tabela SPEC (`tb_tmdb_discover_unified_{env}`) em `glue_catalog.tf` — ela é registrada em runtime pelo Glue AGG
- Mudança em `infra/config/project.json` propaga para nomes em quase todo `infra/*.tf` via `local.tmdb_prefix` — avaliar o impacto antes de alterar
