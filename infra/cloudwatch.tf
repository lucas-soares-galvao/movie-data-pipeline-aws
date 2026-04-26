# Glue Data Quality log groups
resource "aws_cloudwatch_log_group" "glue_data_quality_job_error_log_group" {
  name              = "/${var.glue_data_quality_job_name}/error"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "glue_data_quality_job_output_log_group" {
  name              = "/${var.glue_data_quality_job_name}/output"
  retention_in_days = 1
}
# CloudWatch Log Group da lambda_api

resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.lambda_api_name}"
  retention_in_days = 1
}
