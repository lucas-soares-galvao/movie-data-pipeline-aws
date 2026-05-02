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
		JobName = var.glue_data_quality_job_name
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
		JobName = var.glue_data_quality_job_name
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
		JobName = var.glue_etl_job_name
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
		JobName = var.glue_etl_job_name
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
		FunctionName = var.lambda_api_name
	}
	alarm_actions = [aws_sns_topic.lambda_notifications.arn]
}

# Alarme de sucesso na Lambda (invocações sem erro)
resource "aws_cloudwatch_metric_alarm" "lambda_success_alarm" {
	alarm_name          = "lambda-success-alarm-${var.env}"
	comparison_operator = "GreaterThanThreshold"
	evaluation_periods  = 1
	metric_name         = "Invocations"
	namespace           = "AWS/Lambda"
	period              = 60
	statistic           = "Sum"
	threshold           = 0
	alarm_description   = "Notifica por e-mail quando a Lambda executa com sucesso."
	dimensions = {
		FunctionName = var.lambda_api_name
	}
	alarm_actions = [aws_sns_topic.lambda_notifications.arn]
	ok_actions    = [aws_sns_topic.lambda_notifications.arn]
}

# Exemplo de regra EventBridge que envia para SNS ao sucesso de execução (ajuste event_pattern conforme seu caso)
resource "aws_cloudwatch_event_rule" "eventbridge_success" {
	name        = "eventbridge-success-rule-${var.env}"
	description = "Notifica por e-mail quando EventBridge executa com sucesso."
	event_pattern = <<EOF
{
	"source": ["aws.events"],
	"detail-type": ["Scheduled Event"],
	"detail": {
		"status": ["SUCCESS"]
	}
}
EOF
}

resource "aws_cloudwatch_event_target" "eventbridge_success_sns" {
	rule      = aws_cloudwatch_event_rule.eventbridge_success.name
	target_id = "SendToSNS"
	arn       = aws_sns_topic.eventbridge_notifications.arn
}
