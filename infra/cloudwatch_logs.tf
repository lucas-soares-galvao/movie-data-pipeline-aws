# Raciocinio: provisiona grupos de logs com retencao controlada para observabilidade e custo.
# A variavel log_retention_days permite configurar retencao diferente por ambiente:
#   dev  -> 1 dia  (economiza custo; logs nao precisam durar)
#   prod -> 30 dias (permite investigar incidentes que aparecem dias depois)

resource "aws_cloudwatch_log_group" "glue_etl_error" {
	name              = "/${local.envs.glue_etl_job_name}/error"
	retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "glue_etl_output" {
	name              = "/${local.envs.glue_etl_job_name}/output"
	retention_in_days = var.log_retention_days
}
# Grupos de logs do Glue Data Quality
resource "aws_cloudwatch_log_group" "glue_data_quality_error" {
	name              = "/${local.envs.glue_data_quality_job_name}/error"
	retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "glue_data_quality_output" {
	name              = "/${local.envs.glue_data_quality_job_name}/output"
	retention_in_days = var.log_retention_days
}
# Grupo de logs do CloudWatch para a lambda_api
resource "aws_cloudwatch_log_group" "lambda_log" {
	name              = "/aws/lambda/${local.envs.lambda_api_name}"
	retention_in_days = var.log_retention_days
}

# Grupos de logs do Glue AGG
resource "aws_cloudwatch_log_group" "glue_agg_error" {
	name              = "/${local.envs.glue_agg_job_name}/error"
	retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "glue_agg_output" {
	name              = "/${local.envs.glue_agg_job_name}/output"
	retention_in_days = var.log_retention_days
}
