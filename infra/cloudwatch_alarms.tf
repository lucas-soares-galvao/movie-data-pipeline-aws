# Raciocinio: define alarmes operacionais para falhas criticas da Lambda e resposta rapida.

resource "aws_cloudwatch_metric_alarm" "lambda_error_alarm" {
  alarm_name          = "lambda-error-alarm-${var.env}"
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
}

# Alarme de sucesso na Lambda (invocações sem erro)
resource "aws_cloudwatch_metric_alarm" "lambda_success_alarm" {
  alarm_name          = "lambda-success-alarm-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  alarm_description   = "Notifica por e-mail quando a Lambda executa com sucesso."
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "invocations"
    return_data = false

    metric {
      metric_name = "Invocations"
      namespace   = "AWS/Lambda"
      period      = 60
      stat        = "Sum"
      dimensions = {
        FunctionName = local.envs.lambda_api_name
      }
    }
  }

  metric_query {
    id          = "errors"
    return_data = false

    metric {
      metric_name = "Errors"
      namespace   = "AWS/Lambda"
      period      = 60
      stat        = "Sum"
      dimensions = {
        FunctionName = local.envs.lambda_api_name
      }
    }
  }

  metric_query {
    id          = "success"
    expression  = "invocations-errors"
    label       = "LambdaSuccessfulInvocations"
    return_data = true
  }
}

# Alarme de falha no EventBridge (somando as duas regras agendadas da pipeline)
resource "aws_cloudwatch_metric_alarm" "eventbridge_failed_alarm" {
  alarm_name          = "eventbridge-failed-alarm-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  alarm_description   = "Alerta por e-mail quando o EventBridge falha ao invocar o alvo da pipeline."
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "movie_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_movie.name
      }
    }
  }

  metric_query {
    id          = "tv_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_tv.name
      }
    }
  }

  metric_query {
    id          = "total_failed"
    expression  = "movie_failed+tv_failed"
    label       = "EventBridgeFailedInvocations"
    return_data = true
  }
}

# Alarme de sucesso no EventBridge (invocações efetivas sem falha, somando as duas regras)
resource "aws_cloudwatch_metric_alarm" "eventbridge_success_alarm" {
  alarm_name          = "eventbridge-success-alarm-${var.env}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  alarm_description   = "Notifica por e-mail quando o EventBridge executa com sucesso."
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "movie_invocations"
    return_data = false

    metric {
      metric_name = "Invocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_movie.name
      }
    }
  }

  metric_query {
    id          = "tv_invocations"
    return_data = false

    metric {
      metric_name = "Invocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_tv.name
      }
    }
  }

  metric_query {
    id          = "movie_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_movie.name
      }
    }
  }

  metric_query {
    id          = "tv_failed"
    return_data = false

    metric {
      metric_name = "FailedInvocations"
      namespace   = "AWS/Events"
      period      = 60
      stat        = "Sum"
      dimensions = {
        RuleName = aws_cloudwatch_event_rule.lambda_api_tv.name
      }
    }
  }

  metric_query {
    id          = "total_success"
    expression  = "(movie_invocations+tv_invocations)-(movie_failed+tv_failed)"
    label       = "EventBridgeSuccessfulInvocations"
    return_data = true
  }
}

# Notificação customizada de falha da Lambda (quando alarme entra em ALARM)
resource "aws_cloudwatch_event_rule" "lambda_alarm_failed_state_change" {
  name        = "lambda-alarm-failed-state-change-${var.env}"
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

# Notificação customizada de sucesso da Lambda (ALARM/OK)
resource "aws_cloudwatch_event_rule" "lambda_alarm_success_state_change" {
  name        = "lambda-alarm-success-state-change-${var.env}"
  description = "Notifica mudanças de estado de sucesso da Lambda com motivo detalhado"

  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [aws_cloudwatch_metric_alarm.lambda_success_alarm.alarm_name]
      state = {
        value = ["ALARM", "OK"]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "lambda_alarm_success_state_change_target" {
  rule      = aws_cloudwatch_event_rule.lambda_alarm_success_state_change.name
  target_id = "lambda-alarm-success-sns"
  arn       = aws_sns_topic.lambda_success_notifications.arn

  input_transformer {
    input_paths = {
      alarm_name = "$.detail.alarmName"
      state      = "$.detail.state.value"
      reason     = "$.detail.state.reason"
      timestamp  = "$.detail.state.timestamp"
      region     = "$.region"
    }

    input_template = local.lambda_alarm_success_input_template
  }
}

# Notificação customizada de falha do EventBridge (quando alarme entra em ALARM)
resource "aws_cloudwatch_event_rule" "eventbridge_alarm_failed_state_change" {
  name        = "eventbridge-alarm-failed-state-change-${var.env}"
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

# Notificação customizada de sucesso do EventBridge (ALARM/OK)
resource "aws_cloudwatch_event_rule" "eventbridge_alarm_success_state_change" {
  name        = "eventbridge-alarm-success-state-change-${var.env}"
  description = "Notifica mudanças de estado de sucesso do EventBridge com motivo detalhado"

  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [aws_cloudwatch_metric_alarm.eventbridge_success_alarm.alarm_name]
      state = {
        value = ["ALARM", "OK"]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "eventbridge_alarm_success_state_change_target" {
  rule      = aws_cloudwatch_event_rule.eventbridge_alarm_success_state_change.name
  target_id = "eventbridge-alarm-success-sns"
  arn       = aws_sns_topic.eventbridge_success_notifications.arn

  input_transformer {
    input_paths = {
      alarm_name = "$.detail.alarmName"
      state      = "$.detail.state.value"
      reason     = "$.detail.state.reason"
      timestamp  = "$.detail.state.timestamp"
      region     = "$.region"
    }

    input_template = local.eventbridge_alarm_success_input_template
  }
}
