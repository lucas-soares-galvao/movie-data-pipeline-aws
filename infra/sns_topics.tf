# SNS Topic para notificações do Glue Data Quality
resource "aws_sns_topic" "glue_data_quality_notifications" {
	name = "glue-data-quality-notifications"
}

# Assinatura de e-mail no SNS para Glue Data Quality
resource "aws_sns_topic_subscription" "glue_data_quality_email" {
	topic_arn = aws_sns_topic.glue_data_quality_notifications.arn
	protocol  = "email"
	endpoint  = var.glue_data_quality_notification_email
}

# SNS Topic para notificações do Glue ETL
resource "aws_sns_topic" "glue_etl_notifications" {
	name = "glue-etl-notifications"
}

# Assinatura de e-mail no SNS para Glue ETL
resource "aws_sns_topic_subscription" "glue_etl_email" {
	topic_arn = aws_sns_topic.glue_etl_notifications.arn
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
