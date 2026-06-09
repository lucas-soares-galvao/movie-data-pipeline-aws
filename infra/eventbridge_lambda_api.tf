# Raciocinio: agenda invocacoes da Lambda por tipo de midia para ingestao recorrente automatica.
# Discover (movie e tv) roda diariamente; genre, configuration e watch_providers_ref rodam semanalmente.

# ─────────────────────────────────────────────
# Regras diárias — apenas discover
# ─────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "lambda_api_movie_discover" {
  name                = "lambda-api-movie-discover-${var.env}"
  description         = "Dispara a Lambda para discover de filmes (diário)"
  # schedule_expression = "cron(00 12 * * ? *)" # Todos os dias as 09:00 (SAO PAULO) / 12:00 (UTC)
  schedule_expression = "cron(55 15 * * ? *)" # Todos os dias as 09:00 (SAO PAULO) / 12:00 (UTC)
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv_discover" {
  name                = "lambda-api-tv-discover-${var.env}"
  description         = "Dispara a Lambda para discover de series (diário)"
  # schedule_expression = "cron(05 12 * * ? *)" # Todos os dias as 09:05 (SAO PAULO) / 12:05 (UTC)
  schedule_expression = "cron(00 16 * * ? *)" # Todos os dias as 09:05 (SAO PAULO) / 12:05 (UTC)
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_target" "lambda_api_movie_discover_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_discover.name
  target_id = "lambda-api-movie-discover"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                            = "movie",
    only_discover                   = true,
    database                        = var.glue_catalog_database_movie_name,
    database_unified                = var.glue_catalog_database_unified_name,
    table_discover_movie            = var.glue_catalog_table_discover_movie_name,
    table_genre_movie               = var.glue_catalog_table_genre_movie_name,
    table_configuration_languages   = var.glue_catalog_table_configuration_languages_name,
    table_watch_providers_ref_movie = var.glue_catalog_table_watch_providers_ref_movie_name
  })
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_discover_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv_discover.name
  target_id = "lambda-api-tv-discover"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                          = "tv",
    only_discover                 = true,
    database                      = var.glue_catalog_database_tv_name,
    database_unified              = var.glue_catalog_database_unified_name,
    table_discover_tv             = var.glue_catalog_table_discover_tv_name,
    table_genre_tv                = var.glue_catalog_table_genre_tv_name,
    table_configuration_countries = var.glue_catalog_table_configuration_countries_name,
    table_watch_providers_ref_tv  = var.glue_catalog_table_watch_providers_ref_tv_name
  })
}

resource "aws_lambda_permission" "allow_eventbridge_movie_discover" {
  statement_id  = "AllowEventBridgeMovieDiscoverExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movie_discover.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv_discover" {
  statement_id  = "AllowEventBridgeTvDiscoverExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv_discover.arn
}

# ─────────────────────────────────────────────
# Regras semanais — payload completo (genre + configuration + watch_providers_ref + discover)
# ─────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "lambda_api_movie_weekly" {
  name                = "lambda-api-movie-weekly-${var.env}"
  description         = "Dispara a Lambda para filmes com payload completo (semanal)"
  # schedule_expression = "cron(00 12 ? * SUN *)" # Todo domingo as 09:00 (SAO PAULO) / 12:00 (UTC)
  schedule_expression = "cron(55 15 * * ? *)" # Todo domingo as 09:00 (SAO PAULO) / 12:00 (UTC)
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv_weekly" {
  name                = "lambda-api-tv-weekly-${var.env}"
  description         = "Dispara a Lambda para series com payload completo (semanal)"
  # schedule_expression = "cron(05 12 ? * SUN *)" # Todo domingo as 09:05 (SAO PAULO) / 12:05 (UTC)
  schedule_expression = "cron(00 16 * * ? *)" # Todo domingo as 09:05 (SAO PAULO) / 12:05 (UTC)
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_target" "lambda_api_movie_weekly_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_weekly.name
  target_id = "lambda-api-movie-weekly"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                            = "movie",
    skip_discover                   = true,
    database                        = var.glue_catalog_database_movie_name,
    database_unified                = var.glue_catalog_database_unified_name,
    table_discover_movie            = var.glue_catalog_table_discover_movie_name,
    table_genre_movie               = var.glue_catalog_table_genre_movie_name,
    table_configuration_languages   = var.glue_catalog_table_configuration_languages_name,
    table_watch_providers_ref_movie = var.glue_catalog_table_watch_providers_ref_movie_name
  })
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_weekly_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv_weekly.name
  target_id = "lambda-api-tv-weekly"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                          = "tv",
    skip_discover                 = true,
    database                      = var.glue_catalog_database_tv_name,
    database_unified              = var.glue_catalog_database_unified_name,
    table_discover_tv             = var.glue_catalog_table_discover_tv_name,
    table_genre_tv                = var.glue_catalog_table_genre_tv_name,
    table_configuration_countries = var.glue_catalog_table_configuration_countries_name,
    table_watch_providers_ref_tv  = var.glue_catalog_table_watch_providers_ref_tv_name
  })
}

resource "aws_lambda_permission" "allow_eventbridge_movie_weekly" {
  statement_id  = "AllowEventBridgeMovieWeeklyExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movie_weekly.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv_weekly" {
  statement_id  = "AllowEventBridgeTvWeeklyExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv_weekly.arn
}
