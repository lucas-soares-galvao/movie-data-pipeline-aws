# Cria o Log Group usado pelo Glue com politica de retencao reduzida.
resource "aws_cloudwatch_log_group" "glue_log_group" {
  # Nome alinhado ao argumento --continuous-log-logGroup do Glue Job.
  name              = "/${var.glue_job_name}/jobs"
  # Remove automaticamente eventos com mais de 1 dia.
  retention_in_days = 1
}
