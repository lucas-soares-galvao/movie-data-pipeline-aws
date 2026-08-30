# Recursos AWS provisionados

> **Ordem de leitura sugerida dos arquivos `.tf`:**
> `provider.tf` → `variables.tf` → `locals.tf` → `s3.tf` → `iam_roles.tf` → `lambda_api.tf` → `glue_etl.tf` → `eventbridge.tf`

## Armazenamento — S3 (`s3.tf`)

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

## Computação — Lambda (`lambda_api.tf`)

- Função Lambda `lambda-api-{env}` com timeout e memória configurados
- Pacote Python gerado por `infra/scripts/build_lambda_package.py` e enviado ao bucket AUX
- Variáveis de ambiente injetadas pelo Terraform (nomes de buckets, jobs, ARN do segredo)

## Computação — Glue Jobs (`glue_etl.tf`, `glue_details.tf`, `glue_agg.tf`, `glue_data_quality.tf`)

4 jobs Glue. Os jobs ETL, Details e AGG são do tipo **PythonShell** (Glue 3.9). O job Data Quality é do tipo **Spark (`glueetl`)** (Glue 5.0, 2 workers G.1X, execução FLEX) — exigido pela API `EvaluateDataQuality` da AWS. Cada job tem:
- Worker type e número de workers configurados por ambiente
- Wheel Python gerado por `infra/scripts/build_glue_wheel.py` e enviado ao bucket AUX
- Wheel compartilhado (`tmdb_shared`, nome configurável via `shared_wheel_name` em `infra/config/project.json`) com funções reutilizadas entre jobs (retry HTTP, triggers), gerado por `shared_src.tf` e referenciado via `--extra-py-files` junto ao wheel do job
- Argumentos padrão definidos no Terraform (buckets, nomes de tabelas, databases)
- Argumentos dinâmicos injetados no momento do `start_job_run` pela Lambda/job anterior

## Catálogo — Glue Catalog (`glue_catalog.tf`)

3 databases e 14 tabelas registradas via Terraform:

| Database | Tabelas |
|---|---|
| `db_tmdb_movie_{env}` | tb_tmdb_discover_movie_{env}, tb_tmdb_genre_movie_{env}, tb_tmdb_configuration_languages_{env}, tb_tmdb_details_movie_{env}, tb_tmdb_watch_providers_movie_{env}, tb_tmdb_watch_providers_ref_movie_{env}, tb_tmdb_now_playing_movie_{env} |
| `db_tmdb_tv_{env}` | tb_tmdb_discover_tv_{env}, tb_tmdb_genre_tv_{env}, tb_tmdb_configuration_countries_{env}, tb_tmdb_details_tv_{env}, tb_tmdb_watch_providers_tv_{env}, tb_tmdb_watch_providers_ref_tv_{env} |
| `db_tmdb_unified_{env}` | tb_tmdb_data_quality_{env} |

> Antes da introdução do prefixo `tmdb`, esses nomes de database/tabela não levavam sufixo de ambiente — uma inconsistência com a seção [Ambientes](overview.md#ambientes), já corrigida: agora `db_tmdb_movie_dev` e `db_tmdb_movie_prod` (por exemplo) são databases distintas.

> `tb_tmdb_discover_unified_{env}` (tabela SPEC) não é declarada via Terraform — é registrada dinamicamente pelo job Glue AGG em runtime.

> A tabela `now_playing` não possui partição de ano — é um snapshot completo sobrescrito semanalmente (`mode=overwrite`), diferente das tabelas `discover` que são particionadas por ano. Inclui os campos `theater_start_date` e `theater_end_date` com a janela de exibição reportada pela API do TMDB.

## Servidor — Lightsail (`lightsail_ia.tf`)

A instância/DNS existe **só em prod** — dev não provisiona VM, key pair, portas ou static IP, controlado por `local.lightsail_prod_enabled` (`locals.tf`), que resolve `false` sempre que `var.env != "prod"`, independente do valor de `lightsail_instance_enabled` no tfvars. Já o IAM user do agente (`local.lightsail_agent_enabled`, controlado por `var.lightsail_agent_enabled`) não tem esse gate de ambiente — existe em dev e prod, para permitir testar `recommend()` localmente contra Athena/Glue reais de dev (ver `app/lightsail_ia/lightsail_ia.md` e `infra/config/export_env_local.sh`) sem misturar credenciais com prod.

- Instância `tmdb-filmbot-prod` para hospedar o app Streamlit. Bundle `micro_3_0` (2 vCPU, 1 GB RAM)
- **Caddy** como proxy reverso na porta 80/443, com domínio parametrizado via `{$FILMBOT_DOMAIN}` no `Caddyfile` (injetado por `EnvironmentFile=.env.caddy`, escrito pelo CI/CD): `filmbot.lsgalvao.com.br`
- Streamlit escuta apenas em `127.0.0.1:8501` (não acessível diretamente pela internet)
- Portas abertas: 22 (SSH — CIDR configurável via `lightsail_ssh_allowed_cidrs`), 80 (redirect HTTP→HTTPS + ACME challenge), 443 (HTTPS — proxy reverso para Streamlit)
- IP estático fixo (`tmdb-filmbot-static-ip-prod`) para URL estável — nunca é alvo de nenhum `terraform destroy` (nem o do scheduler, nem um `apply`/`destroy` completo), então o registro DNS no registro.br é cadastrado uma única vez e nunca precisa ser atualizado.
- IAM user `tmdb-filmbot-agent-{env}` (dev e prod) com acesso mínimo a Athena, S3 SPEC/TEMP, Glue Catalog e CloudWatch Logs
- Swap de 1 GB criado automaticamente no bootstrap (`04_deploy_lightsail.yml`) — necessário no bundle `nano_3_0`/`micro_3_0` para o `pip install`/app não sofrerem OOM kill; aplicado em qualquer bundle, custo de disco desprezível
- Controlado por duas variáveis independentes: `lightsail_instance_enabled` — kill-switch manual da VM dentro de prod (ex.: pausa emergencial de custo), sem efeito em dev, que nunca provisiona instância independente desse valor; e `lightsail_agent_enabled` — liga/desliga só o IAM user do agente (sem custo), válido em dev e prod. Quando a instância está habilitada, o workflow de deploy verifica seu estado via `aws lightsail get-instance` antes de tentar o SSH. Se ela estiver destruída (fora da janela do scheduler), o deploy é **ignorado com warning** em vez de falhar por timeout.

**Agendamento de custo** (`.github/workflows/05_lightsail_scheduler.yml`): o Lightsail cobra a mesma tarifa do bundle tanto em `running` quanto em `stopped` — só parar a instância não economiza nada (confirmado via fatura AWS real). Por isso o scheduler **destrói e recria** a instância (não só liga/desliga), via `terraform apply`/`destroy -target` — o IP estático nunca entra nesse `-target` (persiste sempre).
- Cron automático — desliga todo dia às **00:00 BRT**, liga às **18:00 BRT** seg-sex e **08:00 BRT** sáb-dom. Também aceita `workflow_dispatch` manual (a partir da branch `main`).
- Como `lightsail_instance_enabled` permanece `true` por padrão, qualquer `terraform apply` completo (não-targeted) disparado por um push normal em `main` recria a instância se ela estiver destruída no momento — ou seja, um deploy de código pode religar o servidor fora da janela agendada.

**Identidade de usuários — Cognito** (`lightsail_ia.tf`, mesmo gate `lightsail_agent_enabled` do IAM user do agente acima, dev e prod): `aws_cognito_user_pool.filmbot` guarda os usuários do FilmBot (login por e-mail, sem DynamoDB/RDS próprio — o pool já é o armazenamento persistente). `auto_verified_attributes = ["email"]`: o cadastro dispara um código de confirmação de posse do e-mail (OTP), mas o gate de acesso continua sendo a aprovação manual do admin (`AdminEnableUser`, não mais `AdminConfirmSignUp` — ver `app/lightsail_ia/lightsail_ia.md`). `aws_cognito_user_pool_client.filmbot` sem client secret (chamadas só do backend) e `aws_cognito_user_group.admins` para o grupo de administradores. Sem `email_configuration` — o `lambda_config` (bloco `custom_email_sender`) intercepta o código de cadastro/reenvio/"esqueci a senha" e o entrega via Lambda pelo Gmail, ver seção seguinte.

**Envio do código de verificação — KMS + Lambda** (`kms.tf`, `lambda_cognito_email_sender.tf`, mesmo gate `lightsail_agent_enabled`): o remetente nativo do Cognito é um domínio compartilhado por milhares de outros User Pools da AWS, sem SPF/DKIM/DMARC controlados pelo projeto — o e-mail do código caía quase sempre em spam. `aws_kms_key.cognito_email_sender` (chave simétrica dedicada, rotação anual habilitada) é usada pelo trigger nativo `CUSTOM_EMAIL_SENDER` do Cognito para criptografar o código antes de repassá-lo à Lambda `lambda-cognito-email-sender-{env}`, que descriptografa via AWS Encryption SDK e envia o e-mail pelo Gmail — o mesmo remetente já usado pelas notificações do admin (`notify_user_approved`/`notify_user_rejected`/`notify_user_revoked`), que sai de verdade pelos servidores do Google (SPF/DKIM legítimos do domínio `gmail.com`). Ver `app/lambda_cognito_email_sender/lambda_cognito_email_sender.md` para o racional completo (por que SES foi descartado, por que a lógica de Gmail é duplicada em vez de compartilhada com `lightsail_ia`).

**Notificação de cadastro novo — SNS** (`sns_topics.tf`, tópico 10 de 10, mesmo padrão `protocol = "email"` dos outros 9): `filmbot_new_signup_notifications` avisa o admin por e-mail a cada cadastro que confirma a posse do e-mail (não mais a cada `SignUp`, ver `notify_new_signup()`), publicado diretamente por `infrastructure.py::notify_new_signup()` via boto3 — sem EventBridge no meio, mesmo racional dos outros tópicos publicados diretamente por código Python (ex.: `backfill_success_notifications`).
