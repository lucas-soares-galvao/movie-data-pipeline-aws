# Raciocinio: parametriza o ambiente dev com valores isolados de conta e recursos.
# Os valores sensíveis (tmdb_secret_arn) são injetados pelo CI/CD
# via GitHub Secret AWS_TMDB_SECRET_ARN_DEV e não devem ser commitados.

env             = "dev"
tmdb_secret_arn = "REPLACE_VIA_GITHUB_SECRET_AWS_TMDB_SECRET_ARN_DEV"

# Retencao de logs curta no dev para economizar custo.
# Em dev os logs nao precisam durar; investigamos em tempo real.
log_retention_days = 1
