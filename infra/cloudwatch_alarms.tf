# Raciocinio: define alarmes operacionais para falhas criticas da Lambda e resposta rapida.

resource "aws_cloudwatch_metric_alarm" "lambda_error_alarm" {
  alarm_name          = "${local.tmdb_prefix}-lambda-error-alarm-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Alerta por e-mail quando a Lambda apresenta erro."
  dimensions = {
    FunctionName = local.envs.lambda_api_name
  }
  tags = local.component_tags.lambda_api
}

# Alarme de falha no EventBridge (somando as duas regras agendadas da pipeline)
resource "aws_cloudwatch_metric_alarm" "eventbridge_failed_alarm" {
  alarm_name          = "${local.tmdb_prefix}-eventbridge-failed-alarm-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  alarm_description   = "Alerta por e-mail quando o EventBridge falha ao invocar o alvo da pipeline."
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "movie_weekly_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_movie_weekly.name
      }
    }
  }

  metric_query {
    id          = "tv_weekly_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_tv_weekly.name
      }
    }
  }

  metric_query {
    id          = "movie_monthly_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_movie_monthly.name
      }
    }
  }

  metric_query {
    id          = "tv_monthly_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_tv_monthly.name
      }
    }
  }

  metric_query {
    id          = "total_failed"
    expression  = "movie_weekly_failed+tv_weekly_failed+movie_monthly_failed+tv_monthly_failed"
    label       = "EventBridgeFailedInvocations"
    return_data = true
  }

  tags = local.component_tags.eventbridge
}

# Alarme de falha imediata do Lightsail Scheduler (chamada à API do GitHub via
# API Destination) — só existe em prod, mesmo gate das regras que monitora
# (aws_cloudwatch_event_rule.lightsail_scheduler_start/stop, count-based, não dá
# pra somar nas mesmas metric_query de eventbridge_failed_alarm porque aquele
# alarme não é gateado por ambiente). Complementa eventbridge_dlq_alarm (que já
# cobre estas regras via a mesma DLQ compartilhada, mas só depois de esgotadas
# as tentativas de retry, até 24h depois).
resource "aws_cloudwatch_metric_alarm" "lightsail_scheduler_failed_alarm" {
  count = local.lightsail_prod_enabled ? 1 : 0

  alarm_name          = "${local.tmdb_prefix}-lightsail-scheduler-failed-alarm-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  alarm_description   = "Alerta por e-mail quando o EventBridge falha ao chamar a API do GitHub para ligar/desligar o FilmBot."
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "stop_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lightsail_scheduler_stop[0].name
      }
    }
  }

  metric_query {
    id          = "start_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lightsail_scheduler_start[0].name
      }
    }
  }

  metric_query {
    id          = "total_failed"
    expression  = "stop_failed+start_failed"
    label       = "LightsailSchedulerFailedInvocations"
    return_data = true
  }

  alarm_actions = [aws_sns_topic.eventbridge_failure_notifications.arn]
  tags          = local.component_tags.lightsail_ia
}

# Alarme da DLQ do EventBridge — dispara quando há mensagens na fila (eventos não entregues)
resource "aws_cloudwatch_metric_alarm" "eventbridge_dlq_alarm" {
  alarm_name          = "${local.tmdb_prefix}-eventbridge-dlq-alarm-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Alerta quando o EventBridge falha ao entregar eventos ao target."
  treat_missing_data  = "notBreaching"
  dimensions = {
    QueueName = aws_sqs_queue.eventbridge_dlq.name
  }
  alarm_actions = [aws_sns_topic.eventbridge_failure_notifications.arn]
  tags          = local.component_tags.eventbridge
}

# Alarme de erro do FilmBot (busca de recomendação ou transcrição de áudio) — conta
# ocorrências via filmbot_error_filter (cloudwatch_logs.tf). threshold=0 dispara já na
# primeira ocorrência, mas o alarme só executa a ação na transição OK->ALARM, não a cada
# período em que o valor segue alto — vira "um alerta por incidente", não um e-mail por
# usuário/ocorrência. Sem alarm_actions direto: a notificação segue o mesmo padrão de
# lambda_error_alarm/eventbridge_failed_alarm abaixo — EventBridge captura a mudança de
# estado do alarme e publica no SNS com input_transformer, não o alarme publicando direto.
resource "aws_cloudwatch_metric_alarm" "filmbot_error_alarm" {
  count               = local.lightsail_agent_enabled ? 1 : 0
  alarm_name          = "${local.tmdb_prefix}-filmbot-error-alarm-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FilmBotErrorCount"
  namespace           = "FilmBot"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "Alerta por e-mail quando o FilmBot registra erro de busca de recomendação ou transcrição de áudio."
  tags                = local.component_tags.lightsail_ia
}

# Notificação customizada de erro do FilmBot (quando alarme entra em ALARM)
resource "aws_cloudwatch_event_rule" "filmbot_alarm_failed_state_change" {
  count       = local.lightsail_agent_enabled ? 1 : 0
  name        = "${local.tmdb_prefix}-filmbot-alarm-failed-state-change-${var.env}"
  description = "Notifica mudanças de estado de erro do FilmBot com motivo detalhado"

  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [aws_cloudwatch_metric_alarm.filmbot_error_alarm[0].alarm_name]
      state = {
        value = ["ALARM"]
      }
    }
  })

  tags = local.component_tags.lightsail_ia
}

resource "aws_cloudwatch_event_target" "filmbot_alarm_failed_state_change_target" {
  count     = local.lightsail_agent_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.filmbot_alarm_failed_state_change[0].name
  target_id = "filmbot-alarm-failed-sns"
  arn       = aws_sns_topic.filmbot_error_notifications.arn

  input_transformer {
    input_paths = {
      alarm_name = "$.detail.alarmName"
      state      = "$.detail.state.value"
      reason     = "$.detail.state.reason"
      timestamp  = "$.detail.state.timestamp"
      region     = "$.region"
    }

    input_template = local.filmbot_alarm_failed_input_template
  }
}

# Notificação customizada de falha da Lambda (quando alarme entra em ALARM)
resource "aws_cloudwatch_event_rule" "lambda_alarm_failed_state_change" {
  name        = "${local.tmdb_prefix}-lambda-alarm-failed-state-change-${var.env}"
  description = "Notifica mudanças de estado de falha da Lambda com motivo detalhado"

  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [aws_cloudwatch_metric_alarm.lambda_error_alarm.alarm_name]
      state = {
        value = ["ALARM"]
      }
    }
  })

  tags = local.component_tags.lambda_api
}

resource "aws_cloudwatch_event_target" "lambda_alarm_failed_state_change_target" {
  rule      = aws_cloudwatch_event_rule.lambda_alarm_failed_state_change.name
  target_id = "lambda-alarm-failed-sns"
  arn       = aws_sns_topic.lambda_failure_notifications.arn

  input_transformer {
    input_paths = {
      alarm_name = "$.detail.alarmName"
      state      = "$.detail.state.value"
      reason     = "$.detail.state.reason"
      timestamp  = "$.detail.state.timestamp"
      region     = "$.region"
    }

    input_template = local.lambda_alarm_failed_input_template
  }
}

# Notificação customizada de falha do EventBridge (quando alarme entra em ALARM)
resource "aws_cloudwatch_event_rule" "eventbridge_alarm_failed_state_change" {
  name        = "${local.tmdb_prefix}-eventbridge-alarm-failed-state-change-${var.env}"
  description = "Notifica mudanças de estado de falha do EventBridge com motivo detalhado"

  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [aws_cloudwatch_metric_alarm.eventbridge_failed_alarm.alarm_name]
      state = {
        value = ["ALARM"]
      }
    }
  })

  tags = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_target" "eventbridge_alarm_failed_state_change_target" {
  rule      = aws_cloudwatch_event_rule.eventbridge_alarm_failed_state_change.name
  target_id = "eventbridge-alarm-failed-sns"
  arn       = aws_sns_topic.eventbridge_failure_notifications.arn

  input_transformer {
    input_paths = {
      alarm_name = "$.detail.alarmName"
      state      = "$.detail.state.value"
      reason     = "$.detail.state.reason"
      timestamp  = "$.detail.state.timestamp"
      region     = "$.region"
    }

    input_template = local.eventbridge_alarm_failed_input_template
  }
}
