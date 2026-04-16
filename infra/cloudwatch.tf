resource "aws_cloudwatch_log_group" "glue_log_group" {
  name              = "/${var.glue_job_name}/jobs"
  retention_in_days = 1
}