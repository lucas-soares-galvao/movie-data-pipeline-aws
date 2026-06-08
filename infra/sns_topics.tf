# Raciocinio: configura topicos SNS para notificacoes operacionais da pipeline.

# SNS Topic para notificações de falha do Glue Data Quality
resource "aws_sns_topic" "glue_data_quality_failure_notifications" {
  name         = "glue-data-quality-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - GLUE DATA QUALITY"
  tags         = local.component_tags.glue_data_quality
}

# Assinatura de e-mail no SNS para falha do Glue Data Quality
resource "aws_sns_topic_subscription" "glue_data_quality_failure_email" {
  topic_arn = aws_sns_topic.glue_data_quality_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_data_quality_notification_email
}

# SNS Topic para notificações de falha do Glue ETL
resource "aws_sns_topic" "glue_etl_failure_notifications" {
  name         = "glue-etl-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - GLUE ETL"
  tags         = local.component_tags.glue_etl
}

# Assinatura de e-mail no SNS para falha do Glue ETL
resource "aws_sns_topic_subscription" "glue_etl_failure_email" {
  topic_arn = aws_sns_topic.glue_etl_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_etl_notification_email
}

# SNS Topic para notificações de falha da Lambda
resource "aws_sns_topic" "lambda_failure_notifications" {
  name         = "lambda-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - LAMBDA"
  tags         = local.component_tags.lambda_api
}

# Assinatura de e-mail no SNS para falha da Lambda
resource "aws_sns_topic_subscription" "lambda_failure_email" {
  topic_arn = aws_sns_topic.lambda_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.lambda_notification_email
}

# SNS Topic para notificações de falha do EventBridge
resource "aws_sns_topic" "eventbridge_failure_notifications" {
  name         = "eventbridge-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - EVENTBRIDGE"
  tags         = local.component_tags.eventbridge
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
  display_name = "[${upper(var.env)}] PIPELINE - SUCESSO FINAL"
  tags         = local.component_tags.glue_agg
}

resource "aws_sns_topic_subscription" "glue_agg_success_email" {
  topic_arn = aws_sns_topic.glue_agg_success_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_agg_notification_email
}

# SNS Topic para notificações de falha do Glue AGG
resource "aws_sns_topic" "glue_agg_failure_notifications" {
  name         = "glue-agg-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - GLUE AGG"
  tags         = local.component_tags.glue_agg
}

resource "aws_sns_topic_subscription" "glue_agg_failure_email" {
  topic_arn = aws_sns_topic.glue_agg_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_agg_notification_email
}

# SNS Topic para notificações de falha do Glue Details
resource "aws_sns_topic" "glue_details_failure_notifications" {
  name         = "glue-details-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - GLUE DETAILS"
  tags         = local.component_tags.glue_details
}

resource "aws_sns_topic_subscription" "glue_details_failure_email" {
  topic_arn = aws_sns_topic.glue_details_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_details_notification_email
}
