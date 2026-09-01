# =============================================================================
# lightsail_scheduler_trigger.tf — Disparo pontual do Lightsail Scheduler via AWS
#
# O GitHub Actions documenta que o trigger `schedule:` pode atrasar em
# períodos de alta carga (especialmente no início de cada hora — exatamente
# o horário usado pelos dois cron de 05_lightsail_scheduler.yml). Este
# arquivo substitui o `schedule:` do GitHub por uma EventBridge Rule (o
# mesmo motor de cron já usado no resto do projeto, ver eventbridge.tf) que
# chama a API REST do GitHub (workflow_dispatch) via API Destination —
# reaproveitando o input `action: start|stop` que o workflow já aceita.
#
# Só existe em prod — mesmo gate (`local.lightsail_prod_enabled`) usado no
# resto de lightsail_ia.tf, já que o FilmBot não existe em dev.
# =============================================================================

# Conexão de autenticação (Bearer token) usada pela API Destination. O valor
# do token é armazenado pela própria AWS no Secrets Manager; não editar
# infra/envs/*/terraform.tfvars com o valor real (ver
# especialista-seguranca-segredos) — ele chega via -var no CI/CD.
resource "aws_cloudwatch_event_connection" "lightsail_scheduler_github" {
  count = local.lightsail_prod_enabled ? 1 : 0

  name               = local.envs.lightsail_scheduler_connection_name
  description        = "Bearer token (fine-grained PAT) para disparar workflow_dispatch via API do GitHub"
  authorization_type = "API_KEY"

  auth_parameters {
    api_key {
      key   = "Authorization"
      value = "Bearer ${var.github_workflow_dispatch_token}"
    }

    invocation_http_parameters {
      header {
        key   = "Accept"
        value = "application/vnd.github+json"
      }
      header {
        key   = "X-GitHub-Api-Version"
        value = "2022-11-28"
      }
    }
  }
}

resource "aws_cloudwatch_event_api_destination" "lightsail_scheduler_github" {
  count = local.lightsail_prod_enabled ? 1 : 0

  name                             = local.envs.lightsail_scheduler_api_destination_name
  description                      = "Dispara 05_lightsail_scheduler.yml via workflow_dispatch"
  invocation_endpoint              = "https://api.github.com/repos/${local.project_config.github_repo}/actions/workflows/05_lightsail_scheduler.yml/dispatches"
  http_method                      = "POST"
  invocation_rate_limit_per_second = 1
  connection_arn                   = aws_cloudwatch_event_connection.lightsail_scheduler_github[0].arn
}

# Role de execução que a EventBridge Rule assume para invocar a API
# Destination — nomeada com o prefixo tmdb-*, já coberto pela condição
# iam:PassedToService da policy iam_cicd (ver infra/iam_cicd.tf).
resource "aws_iam_role" "lightsail_scheduler_eventbridge" {
  count = local.lightsail_prod_enabled ? 1 : 0

  name = local.envs.lightsail_scheduler_iam_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "sts:AssumeRole"
      },
    ]
  })

  depends_on = [terraform_data.cicd_policies_ready]
  tags       = merge(local.default_resource_tags, local.component_tags.lightsail_ia)
}

resource "aws_iam_role_policy" "lightsail_scheduler_invoke_api_destination" {
  count = local.lightsail_prod_enabled ? 1 : 0

  name = "invoke-api-destination"
  role = aws_iam_role.lightsail_scheduler_eventbridge[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "events:InvokeApiDestination"
        Resource = aws_cloudwatch_event_api_destination.lightsail_scheduler_github[0].arn
      },
    ]
  })
}

# Agenda de desligar — 00:00 BRT diário (03:00 UTC)
resource "aws_cloudwatch_event_rule" "lightsail_scheduler_stop" {
  count = local.lightsail_prod_enabled ? 1 : 0

  name                = local.envs.lightsail_scheduler_rule_stop_name
  description         = "Dispara 05_lightsail_scheduler.yml (action=stop) às 00:00 BRT"
  schedule_expression = "cron(0 3 * * ? *)" # 00:00 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.lightsail_ia
}

# Agenda de ligar — 08:00 BRT diário (11:00 UTC)
resource "aws_cloudwatch_event_rule" "lightsail_scheduler_start" {
  count = local.lightsail_prod_enabled ? 1 : 0

  name                = local.envs.lightsail_scheduler_rule_start_name
  description         = "Dispara 05_lightsail_scheduler.yml (action=start) às 08:00 BRT"
  schedule_expression = "cron(0 11 * * ? *)" # 08:00 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.lightsail_ia
}

resource "aws_cloudwatch_event_target" "lightsail_scheduler_stop" {
  count = local.lightsail_prod_enabled ? 1 : 0

  rule      = aws_cloudwatch_event_rule.lightsail_scheduler_stop[0].name
  target_id = "lightsail-scheduler-stop"
  arn       = aws_cloudwatch_event_api_destination.lightsail_scheduler_github[0].arn
  role_arn  = aws_iam_role.lightsail_scheduler_eventbridge[0].arn

  input = jsonencode({
    ref    = "main"
    inputs = { action = "stop" }
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}

resource "aws_cloudwatch_event_target" "lightsail_scheduler_start" {
  count = local.lightsail_prod_enabled ? 1 : 0

  rule      = aws_cloudwatch_event_rule.lightsail_scheduler_start[0].name
  target_id = "lightsail-scheduler-start"
  arn       = aws_cloudwatch_event_api_destination.lightsail_scheduler_github[0].arn
  role_arn  = aws_iam_role.lightsail_scheduler_eventbridge[0].arn

  input = jsonencode({
    ref    = "main"
    inputs = { action = "start" }
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}
