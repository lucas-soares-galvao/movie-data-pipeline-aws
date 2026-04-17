# Cria grupos de log por job para separar erro e saida com retencao reduzida.
resource "aws_cloudwatch_log_group" "glue_job_error_log_group" {
  for_each = local.glue_jobs

  name              = "/${each.value.job_name}/error"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "glue_job_output_log_group" {
  for_each = local.glue_jobs

  name              = "/${each.value.job_name}/output"
  retention_in_days = 1
}
