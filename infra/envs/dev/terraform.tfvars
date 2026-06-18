# Raciocinio: parametriza o ambiente dev com valores isolados de conta e recursos.
# Os valores sensíveis (tmdb_secret_arn) são injetados pelo CI/CD
# via GitHub Secret AWS_TMDB_SECRET_ARN_DEV e não devem ser commitados.

env             = "dev"
tmdb_secret_arn = "REPLACE_VIA_GITHUB_SECRET_AWS_TMDB_SECRET_ARN_DEV"

# Instância Lightsail desabilitada em dev — usar desenvolvimento local.
# Para reativar: mudar para true e fazer push no develop.
lightsail_enabled           = false
lightsail_ssh_allowed_cidrs = ["0.0.0.0/0"]

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
