# Raciocínio: desliga a instância Lightsail às 23:00 BRT e a reinicia às 08:00 BRT
# para economizar ~37% do custo mensal sem prejuízo de disponibilidade diurna.
# Ativo apenas quando var.lightsail_enabled = true (produção).

# ── Pacote da Lambda (.zip sem dependências externas) ─────────────────────────

data "archive_file" "lightsail_scheduler_bundle" {
  count       = var.lightsail_enabled ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/lightsail_scheduler_bundle.zip"
  source_file = "${path.root}/../app/lambda_lightsail_scheduler/main.py"
}

# ── IAM Role para a Lambda ────────────────────────────────────────────────────

resource "aws_iam_role" "lightsail_scheduler" {
  count = var.lightsail_enabled ? 1 : 0
  name  = "lightsail-scheduler-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = local.component_tags.lightsail_scheduler
}

# Permissão para parar/iniciar a instância Lightsail específica
resource "aws_iam_role_policy" "lightsail_scheduler_control" {
  count = var.lightsail_enabled ? 1 : 0
  name  = "lightsail-scheduler-control-${var.env}"
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
      Resource = "*"
    }]
  })
}

# Permissão para escrever logs no CloudWatch
resource "aws_iam_role_policy" "lightsail_scheduler_logs" {
  count = var.lightsail_enabled ? 1 : 0
  name  = "lightsail-scheduler-logs-${var.env}"
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
        "arn:aws:logs:*:*:log-group:/aws/lambda/lightsail-scheduler-${var.env}",
        "arn:aws:logs:*:*:log-group:/aws/lambda/lightsail-scheduler-${var.env}:log-stream:*",
      ]
    }]
  })
}

# ── CloudWatch Log Group ──────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "lightsail_scheduler" {
  count             = var.lightsail_enabled ? 1 : 0
  name              = "/aws/lambda/lightsail-scheduler-${var.env}"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.lightsail_scheduler
}

# ── Lambda Function ───────────────────────────────────────────────────────────

resource "aws_lambda_function" "lightsail_scheduler" {
  count         = var.lightsail_enabled ? 1 : 0
  function_name = "lightsail-scheduler-${var.env}"
  role          = aws_iam_role.lightsail_scheduler[0].arn
  handler       = "main.lambda_handler"
  runtime       = "python3.11"
  architectures = ["arm64"]
  timeout       = 30

  filename         = data.archive_file.lightsail_scheduler_bundle[0].output_path
  source_code_hash = data.archive_file.lightsail_scheduler_bundle[0].output_base64sha256

  environment {
    variables = {
      LIGHTSAIL_INSTANCE_NAME = "${var.lightsail_instance_name}-${var.env}"
    }
  }

  tags = local.component_tags.lightsail_scheduler

  depends_on = [
    aws_iam_role_policy.lightsail_scheduler_logs,
    aws_iam_role_policy.lightsail_scheduler_control,
    aws_cloudwatch_log_group.lightsail_scheduler,
  ]
}

# ── EventBridge: parar às 23:00 BRT (02:00 UTC) ──────────────────────────────

resource "aws_cloudwatch_event_rule" "lightsail_stop" {
  count               = var.lightsail_enabled ? 1 : 0
  name                = "lightsail-stop-${var.env}"
  description         = "Para a instância Lightsail FilmBot às 23:00 BRT"
  schedule_expression = "cron(00 02 * * ? *)"
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

# ── EventBridge: iniciar às 08:00 BRT (11:00 UTC) ────────────────────────────

resource "aws_cloudwatch_event_rule" "lightsail_start" {
  count               = var.lightsail_enabled ? 1 : 0
  name                = "lightsail-start-${var.env}"
  description         = "Inicia a instância Lightsail FilmBot às 08:00 BRT"
  schedule_expression = "cron(00 11 * * ? *)"
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.lightsail_scheduler
}

resource "aws_cloudwatch_event_target" "lightsail_start_target" {
  count     = var.lightsail_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.lightsail_start[0].name
  target_id = "lightsail-start"
  arn       = aws_lambda_function.lightsail_scheduler[0].arn
  input     = jsonencode({ action = "start" })
}

resource "aws_lambda_permission" "allow_eventbridge_lightsail_start" {
  count         = var.lightsail_enabled ? 1 : 0
  statement_id  = "AllowEventBridgeLightsailStartExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lightsail_scheduler[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lightsail_start[0].arn
}
