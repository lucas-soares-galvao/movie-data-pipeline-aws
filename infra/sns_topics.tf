# =============================================================================
# sns_topics.tf — Tópicos SNS para notificações por email (um por componente)
#
# Tópicos: glue_data_quality_failure/metrics, glue_etl_failure, lambda_failure,
#          eventbridge_failure, glue_agg_success/failure, glue_details_failure,
#          sfn_backfill_failure
# =============================================================================

# =============================================================================
# TÓPICO 1: Falha no Glue Data Quality
# =============================================================================
# Notifica quando regras de qualidade de dados são violadas.
# "display_name" aparece no assunto do email: "[PROD] FALHA - GLUE DATA QUALITY"
resource "aws_sns_topic" "glue_data_quality_failure_notifications" {
  name         = "${local.tmdb_prefix}-glue-data-quality-failure-notifications-${var.env}"
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
  name         = "${local.tmdb_prefix}-glue-data-quality-metrics-notifications-${var.env}"
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
  name         = "${local.tmdb_prefix}-glue-etl-failure-notifications-${var.env}"
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
  name         = "${local.tmdb_prefix}-lambda-failure-notifications-${var.env}"
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
  name         = "${local.tmdb_prefix}-eventbridge-failure-notifications-${var.env}"
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
  name         = "${local.tmdb_prefix}-glue-agg-success-notifications-${var.env}"
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
  name         = "${local.tmdb_prefix}-glue-agg-failure-notifications-${var.env}"
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
  name         = "${local.tmdb_prefix}-glue-details-failure-notifications-${var.env}"
  display_name = "[${upper(var.env)}] FALHA - GLUE DETAILS"
  tags         = local.component_tags.glue_details
}

resource "aws_sns_topic_subscription" "glue_details_failure_email" {
  topic_arn = aws_sns_topic.glue_details_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.glue_details_notification_email
}

# =============================================================================
# TÓPICO 9: Falha no Step Functions Backfill
# =============================================================================
# Notifica quando a execução do backfill histórico falha, é abortada ou expira.
resource "aws_sns_topic" "sfn_backfill_failure_notifications" {
  name         = "${local.tmdb_prefix}-sfn-backfill-failure-notifications-${var.env}"
  display_name = "[${upper(var.env)}] FALHA - STEP FUNCTIONS BACKFILL"
  tags         = local.component_tags.sfn_backfill
}

resource "aws_sns_topic_subscription" "sfn_backfill_failure_email" {
  topic_arn = aws_sns_topic.sfn_backfill_failure_notifications.arn
  protocol  = "email"
  endpoint  = var.sfn_backfill_notification_email
}
