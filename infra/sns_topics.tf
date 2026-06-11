# =============================================================================
# ARQUIVO: sns_topics.tf — Tópicos SNS para Notificações por Email
# =============================================================================
#
# O QUE É AWS SNS?
# SNS (Simple Notification Service) é o serviço de notificações da AWS.
# Funciona como um "sistema de alerta": quando algo acontece (falha ou sucesso),
# o SNS envia uma mensagem para os assinantes cadastrados.
#
# ANALOGIA: Como um grupo de WhatsApp para alertas de sistema.
# - Quando a Lambda falha → mensagem vai para "grupo Lambda"
# - Quando o Glue ETL falha → mensagem vai para "grupo Glue ETL"
# - Quando o pipeline termina com sucesso → mensagem vai para "grupo Sucesso"
#
# MODELO PUBLISH/SUBSCRIBE (Pub/Sub):
# ┌──────────────────┐     publica     ┌──────────────────┐
# │  CloudWatch      │ ──────────────► │   SNS Topic      │
# │  Alarm           │                 │ (canal temático)  │
# └──────────────────┘                 └────────┬─────────┘
#                                               │ entrega
#                                    ┌──────────┼──────────┐
#                                    ▼          ▼          ▼
#                                 Email      Lambda     HTTP
#                               (assinante) (opcional) (optional)
#
# TÓPICOS DESTE PROJETO:
# Um tópico por componente, separando as notificações por responsabilidade:
# 1. glue_data_quality_failure    → Falha no Glue Data Quality
# 2. glue_data_quality_metrics    → Resultado da avaliação de métricas de DQ
# 3. glue_etl_failure             → Falha no Glue ETL
# 4. lambda_failure               → Falha na Lambda
# 5. eventbridge_failure          → Falha no EventBridge
# 6. glue_agg_success             → Sucesso final do pipeline (Glue AGG concluído)
# 7. glue_agg_failure             → Falha no Glue AGG
# 8. glue_details_failure         → Falha no Glue Details
#
# ASSINATURAS (subscriptions):
# Cada tópico tem pelo menos uma assinatura de email.
# Quando um tópico recebe uma mensagem, o SNS envia para todos os assinantes.
# O email de destino vem das variáveis do Terraform (.tfvars) — configurável
# por ambiente (dev e prod podem ter emails diferentes).
# =============================================================================

# =============================================================================
# TÓPICO 1: Falha no Glue Data Quality
# =============================================================================
# Notifica quando regras de qualidade de dados são violadas.
# "display_name" aparece no assunto do email: "[PROD] FALHA - GLUE DATA QUALITY"
resource "aws_sns_topic" "glue_data_quality_failure_notifications" {
  name         = "glue-data-quality-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - GLUE DATA QUALITY"
  tags         = local.component_tags.glue_data_quality
}

# Assinatura de email: quando o tópico receber mensagem, envia para este email.
# "protocol = email" significa entrega via SMTP (email simples).
# O assinante recebe um email de confirmação da AWS e precisa aceitar antes
# de começar a receber notificações.
resource "aws_sns_topic_subscription" "glue_data_quality_failure_email" {
  topic_arn = aws_sns_topic.glue_data_quality_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_data_quality_notification_email
}

# =============================================================================
# TÓPICO 2: Resultado de Métricas do Glue Data Quality
# =============================================================================
# Notifica com o resumo da avaliação de métricas (Passed/Failed por regra).
resource "aws_sns_topic" "glue_data_quality_metrics_notifications" {
  name         = "glue-data-quality-metrics-notifications"
  display_name = "[${upper(var.env)}] QUALIDADE - AVALIAÇÃO DE MÉTRICAS"
  tags         = local.component_tags.glue_data_quality
}

resource "aws_sns_topic_subscription" "glue_data_quality_metrics_email" {
  topic_arn = aws_sns_topic.glue_data_quality_metrics_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_data_quality_metrics_notification_email
}

# =============================================================================
# TÓPICO 3: Falha no Glue ETL
# =============================================================================
# Notifica quando o job de transformação JSON → Parquet falha.
resource "aws_sns_topic" "glue_etl_failure_notifications" {
  name         = "glue-etl-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - GLUE ETL"
  tags         = local.component_tags.glue_etl
}

resource "aws_sns_topic_subscription" "glue_etl_failure_email" {
  topic_arn = aws_sns_topic.glue_etl_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_etl_notification_email
}

# =============================================================================
# TÓPICO 4: Falha na Lambda
# =============================================================================
# Notifica quando a função Lambda falha (erro no código, timeout, etc.).
resource "aws_sns_topic" "lambda_failure_notifications" {
  name         = "lambda-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - LAMBDA"
  tags         = local.component_tags.lambda_api
}

resource "aws_sns_topic_subscription" "lambda_failure_email" {
  topic_arn = aws_sns_topic.lambda_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.lambda_notification_email
}

# =============================================================================
# TÓPICO 5: Falha no EventBridge
# =============================================================================
# Notifica quando o agendador EventBridge não consegue disparar a Lambda.
resource "aws_sns_topic" "eventbridge_failure_notifications" {
  name         = "eventbridge-failure-notifications"
  display_name = "[${upper(var.env)}] FALHA - EVENTBRIDGE"
  tags         = local.component_tags.eventbridge
}

resource "aws_sns_topic_subscription" "eventbridge_failure_email" {
  topic_arn = aws_sns_topic.eventbridge_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.eventbridge_notification_email
}

# =============================================================================
# TÓPICO 6: Sucesso Final do Pipeline (Glue AGG concluído)
# =============================================================================
# Este é o email mais importante: confirma que TODO o pipeline rodou com sucesso.
# O Glue AGG é a última etapa — quando ele termina, os dados estão prontos
# na camada SPEC para o FilmBot consumir.
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

# =============================================================================
# TÓPICO 7: Falha no Glue AGG
# =============================================================================
# Notifica quando a agregação final falha. O mesmo email recebe tanto
# sucesso quanto falha do AGG — permite monitorar o ciclo completo.
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

# =============================================================================
# TÓPICO 8: Falha no Glue Details
# =============================================================================
# Notifica quando o job de enriquecimento de detalhes falha.
# (runtime de filmes, número de temporadas de séries, plataformas de streaming)
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
