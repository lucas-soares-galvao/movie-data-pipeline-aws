# Raciocínio: desliga a instância Lightsail à 00:00 BRT e a reinicia às 18:00 BRT
# (seg–sex) ou 08:00 BRT (sáb–dom) para economizar custo sem prejuízo de disponibilidade.
# Ativo apenas quando var.lightsail_enabled = true (produção).

data "archive_file" "lightsail_scheduler_bundle" {
  count       = var.lightsail_enabled ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/lightsail_scheduler_bundle.zip"
  source_file = "${path.root}/../app/lambda_lightsail_scheduler/main.py"
}

resource "aws_iam_role" "lightsail_scheduler" {
  count = var.lightsail_enabled ? 1 : 0
  name  = "${local.tmdb_prefix}-lightsail-scheduler-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags       = local.component_tags.lightsail_scheduler
  depends_on = [terraform_data.cicd_policies_ready]
}

resource "aws_iam_role_policy" "lightsail_scheduler_control" {
  count = var.lightsail_enabled ? 1 : 0
  name  = "${local.tmdb_prefix}-lightsail-scheduler-control-${var.env}"
  role  = aws_iam_role.lightsail_scheduler[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "LightsailControl"
      Effect = "Allow"
      Action = [
        "lightsail:StopInstance",
        "lightsail:StartInstance",
        "lightsail:GetInstance",
      ]
      Resource = aws_lightsail_instance.filmbot[0].arn
    }]
  })
}

resource "aws_iam_role_policy" "lightsail_scheduler_logs" {
  count = var.lightsail_enabled ? 1 : 0
  name  = "${local.tmdb_prefix}-lightsail-scheduler-logs-${var.env}"
  role  = aws_iam_role.lightsail_scheduler[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "WriteLightsailSchedulerLogs"
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = [
        "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.tmdb_prefix}-lightsail-scheduler-${var.env}",
        "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.tmdb_prefix}-lightsail-scheduler-${var.env}:log-stream:*",
      ]
    }]
  })
}

resource "aws_cloudwatch_log_group" "lightsail_scheduler" {
  count             = var.lightsail_enabled ? 1 : 0
  name              = "/aws/lambda/${local.tmdb_prefix}-lightsail-scheduler-${var.env}"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.lightsail_scheduler
}

resource "aws_lambda_function" "lightsail_scheduler" {
  count         = var.lightsail_enabled ? 1 : 0
  function_name = "${local.tmdb_prefix}-lightsail-scheduler-${var.env}"
  role          = aws_iam_role.lightsail_scheduler[0].arn
  handler       = "main.lambda_handler"
  runtime       = "python3.11"
  architectures = ["arm64"]
  timeout       = 30

  filename         = data.archive_file.lightsail_scheduler_bundle[0].output_path
  source_code_hash = data.archive_file.lightsail_scheduler_bundle[0].output_base64sha256

  environment {
    variables = {
      LIGHTSAIL_INSTANCE_NAME = local.envs.lightsail_instance_name
    }
  }

  tags = local.component_tags.lightsail_scheduler

  depends_on = [
    aws_iam_role_policy.lightsail_scheduler_logs,
    aws_iam_role_policy.lightsail_scheduler_control,
    aws_cloudwatch_log_group.lightsail_scheduler,
  ]
}

resource "aws_cloudwatch_event_rule" "lightsail_stop" {
  count               = var.lightsail_enabled ? 1 : 0
  name                = "${local.tmdb_prefix}-lightsail-stop-${var.env}"
  description         = "Para a instância Lightsail FilmBot à 00:00 BRT"
  schedule_expression = "cron(00 03 ? * * *)"
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.lightsail_scheduler
}

resource "aws_cloudwatch_event_target" "lightsail_stop_target" {
  count     = var.lightsail_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.lightsail_stop[0].name
  target_id = "lightsail-stop"
  arn       = aws_lambda_function.lightsail_scheduler[0].arn
  input     = jsonencode({ action = "stop" })
}

resource "aws_lambda_permission" "allow_eventbridge_lightsail_stop" {
  count         = var.lightsail_enabled ? 1 : 0
  statement_id  = "AllowEventBridgeLightsailStopExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lightsail_scheduler[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lightsail_stop[0].arn
}

resource "aws_cloudwatch_event_rule" "lightsail_start_weekday" {
  count               = var.lightsail_enabled ? 1 : 0
  name                = "${local.tmdb_prefix}-lightsail-start-weekday-${var.env}"
  description         = "Inicia a instância Lightsail FilmBot às 18:00 BRT (seg–sex)"
  schedule_expression = "cron(00 21 ? * MON-FRI *)"
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.lightsail_scheduler
}

resource "aws_cloudwatch_event_target" "lightsail_start_weekday_target" {
  count     = var.lightsail_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.lightsail_start_weekday[0].name
  target_id = "lightsail-start-weekday"
  arn       = aws_lambda_function.lightsail_scheduler[0].arn
  input     = jsonencode({ action = "start" })
}

resource "aws_lambda_permission" "allow_eventbridge_lightsail_start_weekday" {
  count         = var.lightsail_enabled ? 1 : 0
  statement_id  = "AllowEventBridgeLightsailStartWeekdayExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lightsail_scheduler[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lightsail_start_weekday[0].arn
}

resource "aws_cloudwatch_event_rule" "lightsail_start_weekend" {
  count               = var.lightsail_enabled ? 1 : 0
  name                = "${local.tmdb_prefix}-lightsail-start-weekend-${var.env}"
  description         = "Inicia a instância Lightsail FilmBot às 08:00 BRT (sáb–dom)"
  schedule_expression = "cron(00 11 ? * SAT-SUN *)"
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.lightsail_scheduler
}

resource "aws_cloudwatch_event_target" "lightsail_start_weekend_target" {
  count     = var.lightsail_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.lightsail_start_weekend[0].name
  target_id = "lightsail-start-weekend"
  arn       = aws_lambda_function.lightsail_scheduler[0].arn
  input     = jsonencode({ action = "start" })
}

resource "aws_lambda_permission" "allow_eventbridge_lightsail_start_weekend" {
  count         = var.lightsail_enabled ? 1 : 0
  statement_id  = "AllowEventBridgeLightsailStartWeekendExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lightsail_scheduler[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lightsail_start_weekend[0].arn
}
