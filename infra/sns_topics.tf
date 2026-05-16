# SNS Topic para notificações de sucesso do Glue Data Quality
resource "aws_sns_topic" "glue_data_quality_success_notifications" {
	name = "glue-data-quality-success-notifications"
}

# Assinatura de e-mail no SNS para sucesso do Glue Data Quality
resource "aws_sns_topic_subscription" "glue_data_quality_success_email" {
	topic_arn = aws_sns_topic.glue_data_quality_success_notifications.arn
	protocol  = "email"
	endpoint  = var.glue_data_quality_notification_email
}

# SNS Topic para notificações de falha do Glue Data Quality
resource "aws_sns_topic" "glue_data_quality_failure_notifications" {
	name = "glue-data-quality-failure-notifications"
}

# Assinatura de e-mail no SNS para falha do Glue Data Quality
resource "aws_sns_topic_subscription" "glue_data_quality_failure_email" {
	topic_arn = aws_sns_topic.glue_data_quality_failure_notifications.arn
	protocol  = "email"
	endpoint  = var.glue_data_quality_notification_email
}

# SNS Topic para notificações de sucesso do Glue ETL
resource "aws_sns_topic" "glue_etl_success_notifications" {
	name = "glue-etl-success-notifications"
}

# Assinatura de e-mail no SNS para sucesso do Glue ETL
resource "aws_sns_topic_subscription" "glue_etl_success_email" {
	topic_arn = aws_sns_topic.glue_etl_success_notifications.arn
	protocol  = "email"
	endpoint  = var.glue_etl_notification_email
}

# SNS Topic para notificações de falha do Glue ETL
resource "aws_sns_topic" "glue_etl_failure_notifications" {
	name = "glue-etl-failure-notifications"
}

# Assinatura de e-mail no SNS para falha do Glue ETL
resource "aws_sns_topic_subscription" "glue_etl_failure_email" {
	topic_arn = aws_sns_topic.glue_etl_failure_notifications.arn
	protocol  = "email"
	endpoint  = var.glue_etl_notification_email
}

# SNS Topic para notificações da Lambda
resource "aws_sns_topic" "lambda_notifications" {
	name = "lambda-notifications"
}

# Assinatura de e-mail no SNS para Lambda
resource "aws_sns_topic_subscription" "lambda_email" {
	topic_arn = aws_sns_topic.lambda_notifications.arn
	protocol  = "email"
	endpoint  = var.lambda_notification_email
}

# SNS Topic para notificações de EventBridge
resource "aws_sns_topic" "eventbridge_notifications" {
	name = "eventbridge-notifications"
}

# Assinatura de e-mail no SNS para EventBridge
resource "aws_sns_topic_subscription" "eventbridge_email" {
	topic_arn = aws_sns_topic.eventbridge_notifications.arn
	protocol  = "email"
	endpoint  = var.eventbridge_notification_email
}
