resource "aws_cloudwatch_log_group" "glue_etl_error" {
  name              = "/${local.envs.glue_etl_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_etl
}

resource "aws_cloudwatch_log_group" "glue_etl_output" {
  name              = "/${local.envs.glue_etl_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_etl
}

resource "aws_cloudwatch_log_group" "glue_data_quality_error" {
  name              = "/${local.envs.glue_data_quality_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_data_quality
}

resource "aws_cloudwatch_log_group" "glue_data_quality_output" {
  name              = "/${local.envs.glue_data_quality_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_data_quality
}

resource "aws_cloudwatch_log_group" "lambda_log" {
  name              = "/aws/lambda/${local.envs.lambda_api_name}"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.lambda_api
}

resource "aws_cloudwatch_log_group" "lambda_cognito_email_sender_log" {
  count             = local.lightsail_agent_enabled ? 1 : 0
  name              = "/aws/lambda/${local.envs.lambda_cognito_email_sender_name}"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.lambda_cognito_email_sender
}

resource "aws_cloudwatch_log_group" "glue_agg_error" {
  name              = "/${local.envs.glue_agg_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_agg
}

resource "aws_cloudwatch_log_group" "glue_agg_output" {
  name              = "/${local.envs.glue_agg_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_agg
}

resource "aws_cloudwatch_log_group" "glue_details_error" {
  name              = "/${local.envs.glue_details_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_details
}

resource "aws_cloudwatch_log_group" "glue_details_output" {
  name              = "/${local.envs.glue_details_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_details
}

# Existia sem `count` até a remoção do Lightsail de dev — em prod já está no
# state em endereço "bare". Sem este `moved`, o apply destruiria e recriaria o
# log group, perdendo todo o histórico de logs do FilmBot.
moved {
  from = aws_cloudwatch_log_group.lightsail_filmbot
  to   = aws_cloudwatch_log_group.lightsail_filmbot[0]
}

resource "aws_cloudwatch_log_group" "lightsail_filmbot" {
  count             = local.lightsail_agent_enabled ? 1 : 0
  name              = "/lightsail/${local.envs.lightsail_instance_name}"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.lightsail_ia
}

# Conta ocorrências dos dois erros do agente de recomendação (recommendation.py) para
# alimentar o alarme de erro do FilmBot (ver cloudwatch_alarms.tf). Frases completas
# com acento — a restrição de "multi-byte não suportado" do CloudWatch Logs é
# específica de padrões regex (entre %...%), não de frases entre aspas.
resource "aws_cloudwatch_log_metric_filter" "filmbot_error_filter" {
  count          = local.lightsail_agent_enabled ? 1 : 0
  name           = "${local.tmdb_prefix}-filmbot-error-filter-${var.env}"
  log_group_name = aws_cloudwatch_log_group.lightsail_filmbot[0].name
  pattern        = "?\"Erro ao buscar recomendações\" ?\"Erro ao transcrever áudio\""

  metric_transformation {
    name          = "FilmBotErrorCount"
    namespace     = "FilmBot"
    value         = "1"
    default_value = "0"
  }
}
