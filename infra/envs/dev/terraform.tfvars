# Raciocinio: parametriza o ambiente dev com valores isolados de conta e recursos.
# Os valores sensíveis (filmbot_secret_arn) são injetados pelo CI/CD
# via GitHub Secret AWS_FILMBOT_SECRET_ARN_DEV e não devem ser commitados.

env = "dev"

# Agente FilmBot (IAM user + secret access + log group) habilitado em dev pra
# testar recommend() localmente contra Athena/Glue reais de dev. Instância/DNS
# continuam só em prod — redundante manter false aqui (env == "dev" já corta
# via local.lightsail_prod_enabled em infra/locals.tf), mas documenta a intenção.
lightsail_agent_enabled     = true
lightsail_instance_enabled  = false
lightsail_ssh_allowed_cidrs = ["0.0.0.0/0"] # var sem default — precisa de valor mesmo não usado

# Retencao de logs curta no dev para economizar custo.
# Em dev os logs nao precisam durar; investigamos em tempo real.
log_retention_days = 1

# E-mails de notificacao SNS por componente.
glue_agg_notification_email                  = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
glue_details_notification_email              = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
glue_data_quality_notification_email         = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
glue_data_quality_metrics_notification_email = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
glue_etl_notification_email                  = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
lambda_notification_email                    = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
eventbridge_notification_email               = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
backfill_notification_email                  = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"

# ARN do segredo unificado no Secrets Manager (tmdb_api_key, llm_api_key, filmbot_password).
# Valor real injetado pelo CI/CD via GitHub Secret AWS_FILMBOT_SECRET_ARN_DEV.
filmbot_secret_arn = "REPLACE_VIA_GITHUB_SECRET_AWS_FILMBOT_SECRET_ARN"
