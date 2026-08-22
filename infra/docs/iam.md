# Permissões — IAM

## Roles e Policies (`iam_roles.tf`, `iam_policies.tf`)

| Role | Usada por | Permissões principais |
|---|---|---|
| `tmdb-lambda-api-{env}` | Lambda API | S3 (SOR, AUX, TEMP restrito a `tmdb/changes/*`), Glue (StartJobRun + GetJobRun — ETL, AGG e Details), Secrets Manager, SSM Parameter Store (GetParameter/PutParameter restrito ao ponteiro do rotation refresh — `infra/ssm.tf`) |
| `tmdb-glue-etl-{env}` | Glue ETL | S3 (SOR, SOT, AUX), Glue Catalog, StartJobRun (DQ, Details) |
| `tmdb-glue-data-quality-{env}` | Glue Data Quality | S3 (SOT, SPEC, DQ), Glue Catalog, SNS (tópicos DQ direto), CloudWatch |
| `tmdb-glue-agg-{env}` | Glue AGG | S3 (SOT, SPEC, TEMP), Glue Catalog, Athena, StartJobRun (DQ) |
| `tmdb-glue-details-{env}` | Glue Details | S3 (SOT, TEMP restrito a `tmdb/athena/glue_details/*` e `tmdb/changes/*` — modo changes), Glue Catalog, Athena, Secrets Manager, StartJobRun (AGG, DQ) |
| `tmdb-filmbot-agent-prod` (user) | Lightsail FilmBot — só prod (dev não provisiona Lightsail) | Athena, S3 (SPEC, TEMP), Glue Catalog, CloudWatch Logs, Secrets Manager |
| `tmdb-backfill-role-{env}` | GitHub Actions — backfill manual (`06_backfill.yml`) | `glue:StartJobRun`/`GetJobRun` (jobs Data Quality e AGG), Athena, Secrets Manager, S3 (checkpoints + tabelas discover/details/referência movie/tv no SOT + JSON bruto no SOR), Glue Catalog (tabelas discover/details/referência movie/tv), Translate/Comprehend |

Políticas com least-privilege: cada role tem acesso apenas aos recursos que realmente precisa.

A Lambda usa uma **policy inline customizada** para logs em vez de `AWSLambdaBasicExecutionRole` (policy gerenciada da AWS). Motivo: a policy gerenciada inclui `logs:CreateLogGroup`, que permitiria à Lambda criar grupos de log sem a retenção configurada pelo Terraform. Com a policy customizada, só permitimos `CreateLogStream` e `PutLogEvents` em grupos que o `cloudwatch_logs.tf` já criou com retenção controlada.

Pelo mesmo princípio, os jobs Glue usam uma **policy compartilhada customizada** (`glue_shared_base`) em vez da managed policy `AWSGlueServiceRole`. Motivo: `AWSGlueServiceRole` concede `glue:*` em `Resource: *`, anulando todas as policies granulares de Catalog, S3 e logs definidas por job. A policy customizada fornece apenas o mínimo para o runtime Glue funcionar: `cloudwatch:PutMetricData` (métricas de job) e acesso S3 aos buckets temporários `aws-glue-*` (necessários para jobs Spark como o Data Quality).

## Permissões do CI/CD (`iam_cicd.tf`)

A role do GitHub Actions (`lsg-github-actions-{env}`) foi originalmente criada **manualmente** e é gerenciada como `aws_iam_role.github_actions` em `iam_cicd.tf`, que também cria e anexa policies managed de privilégio mínimo — 8 em prod, 7 em dev (`cicd-terraform-lightsail-{env}` só existe em prod, já que dev não provisiona nenhum recurso Lightsail — ver `local.lightsail_prod_enabled` em `locals.tf`). Como a role já existia antes do resource, o step "Import existing CI/CD role (one-time state adoption)" em `02_terraform.yml` adota ela no state via `terraform import` antes do plan/apply de cada ambiente (checa `terraform state show` primeiro — no-op depois da primeira adoção); sem isso o Terraform tentaria `CreateRole` nela, que a própria role não tem permissão de fazer contra si mesma. O job também usa `concurrency: group: terraform-{env}` para serializar runs do mesmo ambiente, evitando que dois pushes próximos disputem a adoção da role no state ao mesmo tempo. O nome da role (`cicd_role_name`) e o prefixo das policies (`cicd_policy_prefix`) vêm de `infra/config/project.json` — os valores abaixo são os defaults:

**MaxSessionDuration:** a role tem `max_session_duration = 3600` (1h) fixado no código, e o workflow `06_backfill.yml` não pede `role-duration-seconds` customizado (usa esse mesmo default de 1h da action `aws-actions/configure-aws-credentials`). Backfills históricos podem rodar por horas e a sessão expira antes do fim — em vez de esticar a duração, o step "Run backfill" trata `ExpiredTokenException` especificamente: reassume a role via `aws sts assume-role-with-web-identity` inline (nova sessão de 1h) e retoma o script do checkpoint em S3 (ver `scripts/backfill_shared.py` e a seção `06_backfill.yml` em `estrutura-projeto`).

A policy `cicd-terraform-iam-{env}` concede à própria role permissão para se auto-gerenciar (`iam:UpdateRole`, `iam:UpdateAssumeRolePolicy`, `iam:TagRole`/`UntagRole`), sem poder se criar ou deletar (statement `IAMCICDRoleManagement`).

| Policy | Escopo |
|---|---|
| `cicd-terraform-backend-{env}` | DynamoDB (state lock) + STS (caller identity) |
| `cicd-terraform-s3-{env}` | 6 buckets do projeto + bucket de state |
| `cicd-terraform-iam-{env}` | Roles/policies/users `tmdb-*` + auto-gerenciamento `cicd-terraform-*` |
| `cicd-terraform-compute-{env}` | Lambda, Glue (jobs + catalog) |
| `cicd-terraform-observability-{env}` | EventBridge, CloudWatch (logs + alarms — inclui log groups `/lightsail/tmdb-*`), SNS, SQS (DLQ) |
| `cicd-terraform-lightsail-{env}` | Instância, key pair, static IP em us-east-1 — **só prod** (`count` condicionado a `var.env == "prod"` em `iam_cicd.tf`) |
| `cicd-terraform-ssm-{env}` | Parâmetros SSM do rotation refresh (`/tmdb-pipeline/rotation-year-pointer-*`) + `iam:SimulatePrincipalPolicy` sobre a própria role (usado pelo polling de propagação, ver abaixo) |
| `cicd-terraform-cognito-{env}` | User Pool do FilmBot (`aws_cognito_user_pool`/`_client`/`aws_cognito_user_group`, ver `lightsail_ia.tf`) — `CreateUserPool` com `Resource "*"` (ARN não existe antes da criação), demais actions escopadas ao ARN do pool |

O workflow do GitHub Actions (`02_terraform.yml`) resolve o problema de bootstrap automaticamente: antes do `terraform plan`, um step aplica as policies com `-target` (a de Lightsail só em prod, já que em dev ela não existe), garantindo que a role tenha permissões antes de gerenciar os demais recursos. O step é idempotente — se as policies já existem, é um no-op.

Um recurso `terraform_data.cicd_policies_ready` sincroniza a criação: os buckets S3 e as IAM roles do projeto só são criados **depois** que as policies estejam attachadas à role do GitHub Actions.

Além do polling do workflow (`aws iam list-attached-role-policies`, 12 tentativas de 5s), existe um segundo mecanismo de propagação dentro do próprio Terraform: `null_resource.cicd_policies_propagation`, que testa especificamente a `cicd-terraform-ssm-{env}` via `aws iam simulate-principal-policy` (mesma janela de 60s). Ele existe porque, num ambiente novo, a role cria e anexa essa policy a si mesma no mesmo apply, sujeito à mesma janela de eventual consistency do IAM que motivou o bootstrap do workflow — mas os dois mecanismos não são sincronizados entre si (um verifica via API de propagação de policy, o outro via simulação de permissão). Ao adicionar uma policy de CI/CD nova, atualizar os dois: a lista `-target`/`EXPECTED_POLICIES` do workflow e, se a policy nova também puder ser necessária no mesmo apply em que é criada, considerar se precisa de checagem equivalente à `cicd_policies_propagation`.

## Permissões do backfill manual (`iam_backfill.tf`)

O workflow `06_backfill.yml` (dispatch manual de reprocessamento pontual) usava, até então, a mesma role de CI/CD acima — o que dava a um backfill manual acesso a IAM CRUD, gestão de buckets, Lightsail, etc., sem necessidade real. A role `tmdb-backfill-role-{env}` separa essa responsabilidade com privilégio mínimo, cobrindo exatamente o que os 8 scripts `scripts/backfill_*.py` usam:

Nenhum dos 8 scripts invoca a Lambda API hoje — todos rodam a coleta TMDB e a transformação
equivalente ao Glue ETL/Glue Details diretamente no processo do script, então não existe (nem
nunca precisou existir a partir do momento em que `backfill_discover.py`, o último a depender de
Lambda, passou a rodar in-process) uma policy `lambda:InvokeFunction` para esta role.
`backfill_historico.py` não aparece nas linhas da tabela abaixo por chamada própria — ele só
encadeia `backfill_discover.py`/`backfill_enriquecimento.py` (chama o `main()` de cada um no
mesmo processo), então usa exatamente a união das permissões que os dois já têm, sem exigir
nenhuma policy nova.

| Policy | Escopo |
|---|---|
| `tmdb-backfill-glue-jobs-{env}` | `glue:StartJobRun`/`GetJobRun` restrito aos jobs Data Quality e AGG — disparo fire-and-forget do Data Quality ao final de `backfill_discover.py`/`backfill_enriquecimento.py`/`backfill_data_quality.py`/`backfill_changes.py`, e disparo + polling do AGG pelo workflow ao final de qualquer `table_group` exceto `data_quality` |
| `tmdb-backfill-athena-{env}` | `athena:StartQueryExecution`/`GetQueryExecution`/`GetQueryResults`/`StopQueryExecution`/`GetWorkGroup` restrito ao workgroup `primary` (`backfill_enriquecimento.py`, `backfill_changes.py`) |
| `tmdb-backfill-secrets-{env}` | `secretsmanager:GetSecretValue` restrito ao secret do TMDB (`backfill_discover.py`, `backfill_enriquecimento.py`, `backfill_changes.py`) |
| `tmdb-backfill-s3-{env}` | CRUD restrito ao prefixo `tmdb/backfill_checkpoints/*` no bucket TEMP (todos os scripts, exceto `backfill_referencias.py`/`backfill_changes.py`), ao prefixo `tmdb/changes/*` no bucket TEMP (`backfill_changes.py`), a JSON bruto de discover/genre/configuration/watch_providers_ref no bucket SOR (`backfill_discover.py`, `backfill_referencias.py`) e às tabelas discover/details/referência movie/tv (`backfill_discover.py`, `backfill_referencias.py`, `backfill_traducao.py`) e details/watch_providers movie/tv (`backfill_rename_colunas.py`) no bucket SOT |
| `tmdb-backfill-glue-catalog-{env}` | `GetTable`/`GetPartitions`/`BatchCreatePartition`/`BatchDeletePartition`/`UpdateTable` restrito às tabelas discover, details, watch_providers e referência movie/tv — usado implicitamente pelo `awswrangler` em `backfill_discover.py`, `backfill_referencias.py`, `backfill_traducao.py` e `backfill_rename_colunas.py` — mais `CreateTable`/`DeleteTable` (statement `DeleteCtasTempTable`) restrito a `table/{database}/*` nas databases movie/tv, para a tabela temporária que o Athena CTAS (`ctas_approach=True`) cria e apaga em `resolve_matched_ids_for_changed_ids` (`backfill_changes.py`) — mesmo padrão de `glue_details_catalog` em `iam_policies.tf` |
| `tmdb-backfill-translate-{env}` | `translate:TranslateText`/`comprehend:DetectDominantLanguage` (sem restrição de recurso) — usado quando `TRANSLATE_PROVIDER=aws` é escolhido, e como fallback automático mesmo com o default `"google"` (`backfill_discover.py`, `backfill_referencias.py`, `backfill_enriquecimento.py`, `backfill_traducao.py`, `backfill_changes.py`) |

Diferente da role de CI/CD, a trust policy desta role restringe o `sub` do token OIDC também por branch (`ref:refs/heads/develop` em dev, `ref:refs/heads/main` em prod, casando com a resolução de ambiente feita pelo próprio `06_backfill.yml`), não só por repositório — reforço de segurança possível porque é uma role nova, sem histórico de uso a preservar.

Não há problema de bootstrap circular: a policy `cicd-terraform-iam-{env}` já cobre `role/tmdb-*` (wildcard existente), então a role de CI/CD já pode criar/gerenciar `tmdb-backfill-role-{env}` num apply normal, sem `-target` nem step de bootstrap adicional.

Esta role serve o backfill **manual sob demanda** via scripts (`06_backfill.yml`), assumida via OIDC do GitHub Actions.
