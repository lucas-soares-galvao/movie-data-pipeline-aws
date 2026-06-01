# Raciocinio: configura topicos SNS para notificacoes operacionais da pipeline.

resource "aws_sns_topic" "glue_data_quality_success_notifications" {
  name         = "glue-data-quality-success-notifications"
  display_name = "[${upper(var.env)}] GLUE DATA QUALITY - SUCESSO"
}

# Assinatura de e-mail no SNS para sucesso do Glue Data Quality
resource "aws_sns_topic_subscription" "glue_data_quality_success_email" {
  topic_arn = aws_sns_topic.glue_data_quality_success_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_data_quality_notification_email
}

# SNS Topic para notificações de falha do Glue Data Quality
resource "aws_sns_topic" "glue_data_quality_failure_notifications" {
  name         = "glue-data-quality-failure-notifications"
  display_name = "[${upper(var.env)}] GLUE DATA QUALITY - ERRO"
}

# Assinatura de e-mail no SNS para falha do Glue Data Quality
resource "aws_sns_topic_subscription" "glue_data_quality_failure_email" {
  topic_arn = aws_sns_topic.glue_data_quality_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_data_quality_notification_email
}

# SNS Topic para notificações de sucesso do Glue ETL
resource "aws_sns_topic" "glue_etl_success_notifications" {
  name         = "glue-etl-success-notifications"
  display_name = "[${upper(var.env)}] GLUE ETL - SUCESSO"
}

# Assinatura de e-mail no SNS para sucesso do Glue ETL
resource "aws_sns_topic_subscription" "glue_etl_success_email" {
  topic_arn = aws_sns_topic.glue_etl_success_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_etl_notification_email
}

# SNS Topic para notificações de falha do Glue ETL
resource "aws_sns_topic" "glue_etl_failure_notifications" {
  name         = "glue-etl-failure-notifications"
  display_name = "[${upper(var.env)}] GLUE ETL - ERRO"
}

# Assinatura de e-mail no SNS para falha do Glue ETL
resource "aws_sns_topic_subscription" "glue_etl_failure_email" {
  topic_arn = aws_sns_topic.glue_etl_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_etl_notification_email
}

# SNS Topic para notificações de sucesso da Lambda
resource "aws_sns_topic" "lambda_success_notifications" {
  name         = "lambda-success-notifications"
  display_name = "[${upper(var.env)}] LAMBDA - SUCESSO"
}

# Assinatura de e-mail no SNS para sucesso da Lambda
resource "aws_sns_topic_subscription" "lambda_success_email" {
  topic_arn = aws_sns_topic.lambda_success_notifications.arn
  protocol  = "email"
  endpoint  = var.lambda_notification_email
}

# SNS Topic para notificações de falha da Lambda
resource "aws_sns_topic" "lambda_failure_notifications" {
  name         = "lambda-failure-notifications"
  display_name = "[${upper(var.env)}] LAMBDA - ERRO"
}

# Assinatura de e-mail no SNS para falha da Lambda
resource "aws_sns_topic_subscription" "lambda_failure_email" {
  topic_arn = aws_sns_topic.lambda_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.lambda_notification_email
}

# SNS Topic para notificações de sucesso do EventBridge
resource "aws_sns_topic" "eventbridge_success_notifications" {
  name         = "eventbridge-success-notifications"
  display_name = "[${upper(var.env)}] EVENTBRIDGE - SUCESSO"
}

# Assinatura de e-mail no SNS para sucesso do EventBridge
resource "aws_sns_topic_subscription" "eventbridge_success_email" {
  topic_arn = aws_sns_topic.eventbridge_success_notifications.arn
  protocol  = "email"
  endpoint  = var.eventbridge_notification_email
}

# SNS Topic para notificações de falha do EventBridge
resource "aws_sns_topic" "eventbridge_failure_notifications" {
  name         = "eventbridge-failure-notifications"
  display_name = "[${upper(var.env)}] EVENTBRIDGE - ERRO"
}

# Assinatura de e-mail no SNS para falha do EventBridge
resource "aws_sns_topic_subscription" "eventbridge_failure_email" {
  topic_arn = aws_sns_topic.eventbridge_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.eventbridge_notification_email
}

# SNS Topic para notificações de sucesso do Glue AGG
resource "aws_sns_topic" "glue_agg_success_notifications" {
  name         = "glue-agg-success-notifications"
  display_name = "[${upper(var.env)}] GLUE AGG - SUCESSO"
}

resource "aws_sns_topic_subscription" "glue_agg_success_email" {
  topic_arn = aws_sns_topic.glue_agg_success_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_agg_notification_email
}

# SNS Topic para notificações de falha do Glue AGG
resource "aws_sns_topic" "glue_agg_failure_notifications" {
  name         = "glue-agg-failure-notifications"
  display_name = "[${upper(var.env)}] GLUE AGG - ERRO"
}

resource "aws_sns_topic_subscription" "glue_agg_failure_email" {
  topic_arn = aws_sns_topic.glue_agg_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_agg_notification_email
}
