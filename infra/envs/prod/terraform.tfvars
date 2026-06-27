# Raciocinio: parametriza o ambiente prod com isolamento e naming proprios de producao.
# Os valores sensíveis (filmbot_secret_arn) são injetados pelo CI/CD
# via GitHub Secret AWS_FILMBOT_SECRET_ARN_PROD e não devem ser commitados.

env = "prod"

lightsail_enabled           = true
lightsail_ssh_allowed_cidrs = ["0.0.0.0/0"]

# Retencao de logs mais longa em prod para permitir investigar incidentes
# que aparecem dias depois da execucao (ex.: anomalias em dados historicos).
log_retention_days = 5

# E-mails de notificacao SNS por componente.
glue_agg_notification_email                  = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
glue_details_notification_email              = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
glue_data_quality_notification_email         = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
glue_data_quality_metrics_notification_email = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
glue_etl_notification_email                  = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
lambda_notification_email                    = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
eventbridge_notification_email               = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"
sfn_backfill_notification_email              = "REPLACE_VIA_GITHUB_SECRET_NOTIFICATION_EMAIL"

# ARN do segredo unificado no Secrets Manager (tmdb_api_key, llm_api_key, filmbot_password).
# Valor real injetado pelo CI/CD via GitHub Secret AWS_FILMBOT_SECRET_ARN_PROD.
filmbot_secret_arn = "REPLACE_VIA_GITHUB_SECRET_AWS_FILMBOT_SECRET_ARN"
