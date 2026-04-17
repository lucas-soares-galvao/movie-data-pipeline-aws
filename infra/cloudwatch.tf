# Cria grupos de log por job para separar erro e saida com retencao reduzida.
resource "aws_cloudwatch_log_group" "glue_etl_job_error_log_group" {
  name              = "/${var.glue_etl_job_name}/error"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "glue_etl_job_output_log_group" {
  name              = "/${var.glue_etl_job_name}/output"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "glue_data_quality_job_error_log_group" {
  name              = "/${var.glue_data_quality_job_name}/error"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "glue_data_quality_job_output_log_group" {
  name              = "/${var.glue_data_quality_job_name}/output"
  retention_in_days = 1
}
