# Raciocinio: parametriza o ambiente prod com isolamento e naming proprios de producao.
# Os valores sensíveis (tmdb_secret_arn) são injetados pelo CI/CD
# via GitHub Secret AWS_TMDB_SECRET_ARN_PROD e não devem ser commitados.

env             = "prod"
tmdb_secret_arn = "REPLACE_VIA_GITHUB_SECRET_AWS_TMDB_SECRET_ARN_PROD"

# Retencao de logs mais longa em prod para permitir investigar incidentes
# que aparecem dias depois da execucao (ex.: anomalias em dados historicos).
log_retention_days = 30
