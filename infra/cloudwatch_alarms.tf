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
    id          = "movie_daily_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_movie_daily.name
      }
    }
  }

  metric_query {
    id          = "tv_daily_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_tv_daily.name
      }
    }
  }

  metric_query {
    id          = "movie_week_failed"
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
    id          = "tv_week_failed"
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
    expression  = "movie_daily_failed+tv_daily_failed+movie_week_failed+tv_week_failed"
    label       = "EventBridgeFailedInvocations"
    return_data = true
  }

  tags = local.component_tags.eventbridge
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
