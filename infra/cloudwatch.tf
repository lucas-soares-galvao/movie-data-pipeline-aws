# CloudWatch Log Group da lambda_api

resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.lambda_api_name}"
  retention_in_days = 1
}
