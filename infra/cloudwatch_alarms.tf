# Alarme de falha no Glue Data Quality
resource "aws_cloudwatch_metric_alarm" "glue_data_quality_failed_alarm" {
	alarm_name          = "glue-data-quality-failed-alarm-${var.env}"
	comparison_operator = "GreaterThanThreshold"
	evaluation_periods  = 1
	metric_name         = "Failed"
	namespace           = "AWS/Glue"
	period              = 60
	statistic           = "Sum"
	threshold           = 0
	alarm_description   = "Alerta por e-mail quando o Glue Data Quality falha."
	dimensions = {
		JobName = local.envs.glue_data_quality_job_name
	}
	alarm_actions = [aws_sns_topic.glue_data_quality_notifications.arn]
}

# Alarme de sucesso no Glue Data Quality
resource "aws_cloudwatch_metric_alarm" "glue_data_quality_success_alarm" {
	alarm_name          = "glue-data-quality-success-alarm-${var.env}"
	comparison_operator = "GreaterThanThreshold"
	evaluation_periods  = 1
	metric_name         = "Succeeded"
	namespace           = "AWS/Glue"
	period              = 60
	statistic           = "Sum"
	threshold           = 0
	alarm_description   = "Notifica por e-mail quando o Glue Data Quality executa com sucesso."
	dimensions = {
		JobName = local.envs.glue_data_quality_job_name
	}
	alarm_actions = [aws_sns_topic.glue_data_quality_notifications.arn]
	ok_actions    = [aws_sns_topic.glue_data_quality_notifications.arn]
}

# Alarme de falha no Glue ETL
resource "aws_cloudwatch_metric_alarm" "glue_etl_failed_alarm" {
	alarm_name          = "glue-etl-failed-alarm-${var.env}"
	comparison_operator = "GreaterThanThreshold"
	evaluation_periods  = 1
	metric_name         = "Failed"
	namespace           = "AWS/Glue"
	period              = 60
	statistic           = "Sum"
	threshold           = 0
	alarm_description   = "Alerta por e-mail quando o Glue ETL falha."
	dimensions = {
		JobName = local.envs.glue_etl_job_name
	}
	alarm_actions = [aws_sns_topic.glue_etl_notifications.arn]
}

# Alarme de sucesso no Glue ETL
resource "aws_cloudwatch_metric_alarm" "glue_etl_success_alarm" {
	alarm_name          = "glue-etl-success-alarm-${var.env}"
	comparison_operator = "GreaterThanThreshold"
	evaluation_periods  = 1
	metric_name         = "Succeeded"
	namespace           = "AWS/Glue"
	period              = 60
	statistic           = "Sum"
	threshold           = 0
	alarm_description   = "Notifica por e-mail quando o Glue ETL executa com sucesso."
	dimensions = {
		JobName = local.envs.glue_etl_job_name
	}
	alarm_actions = [aws_sns_topic.glue_etl_notifications.arn]
	ok_actions    = [aws_sns_topic.glue_etl_notifications.arn]
}

# Alarme de erro na Lambda
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
	alarm_actions = [aws_sns_topic.lambda_notifications.arn]
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

	alarm_actions = [aws_sns_topic.lambda_notifications.arn]
	ok_actions    = [aws_sns_topic.lambda_notifications.arn]
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

	alarm_actions = [aws_sns_topic.eventbridge_notifications.arn]
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

	alarm_actions = [aws_sns_topic.eventbridge_notifications.arn]
	ok_actions    = [aws_sns_topic.eventbridge_notifications.arn]
}
