# Raciocinio: provisiona grupos de logs com retencao controlada para observabilidade e custo.

resource "aws_cloudwatch_log_group" "glue_etl_error" {
	name              = "/${local.envs.glue_etl_job_name}/error"
	retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "glue_etl_output" {
	name              = "/${local.envs.glue_etl_job_name}/output"
	retention_in_days = 1
}
# Grupos de logs do Glue Data Quality
resource "aws_cloudwatch_log_group" "glue_data_quality_error" {
	name              = "/${local.envs.glue_data_quality_job_name}/error"
	retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "glue_data_quality_output" {
	name              = "/${local.envs.glue_data_quality_job_name}/output"
	retention_in_days = 1
}
# Grupo de logs do CloudWatch para a lambda_api
resource "aws_cloudwatch_log_group" "lambda_log" {
	name              = "/aws/lambda/${local.envs.lambda_api_name}"
	retention_in_days = 1
}
