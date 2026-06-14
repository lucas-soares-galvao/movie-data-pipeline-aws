# =============================================================================
# eventbridge_lambda_api.tf — Agendamento automático da Lambda
#
# Estratégia: diária (só discover) + semanal (referências: gêneros, países, etc.)
# DESABILITADO em dev (local.eventbridge_schedule_state = "DISABLED") — invoque a Lambda manualmente.
# =============================================================================

# =============================================================================
# REGRAS DIÁRIAS — Apenas Discover (Descoberta de Novos Títulos)
# =============================================================================
# Discover = busca na API TMDB os filmes/séries mais populares.
# Roda diariamente para capturar novos lançamentos e atualizações de popularidade.
#
# Horários separados (12:00 e 12:05 UTC) para não disparar duas Lambdas
# simultaneamente — evita concorrência desnecessária nas chamadas à API TMDB.
# =============================================================================

# Agenda diária para discover de FILMES — 09:00 horário de Brasília (12:00 UTC)
resource "aws_cloudwatch_event_rule" "lambda_api_movie_discover" {
  name        = "lambda-api-movie-discover-${var.env}"
  description = "Dispara a Lambda para discover de filmes (diário)"
  # schedule_expression = "cron(00 12 * * ? *)" # Todos os dias às 12:00 UTC / 09:00 BRT
  schedule_expression = "cron(15 04 * * ? *)" # Todos os dias às 20:30 UTC / 17:30 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

# Agenda diária para discover de SÉRIES — 09:05 horário de Brasília (12:05 UTC)
resource "aws_cloudwatch_event_rule" "lambda_api_tv_discover" {
  name        = "lambda-api-tv-discover-${var.env}"
  description = "Dispara a Lambda para discover de series (diário)"
  # schedule_expression = "cron(05 12 * * ? *)" # Todos os dias às 12:05 UTC / 09:05 BRT
  schedule_expression = "cron(20 04 * * ? *)" # Todos os dias às 20:35 UTC / 17:35 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

# Vincula a regra de filmes à Lambda e define o payload (JSON enviado ao handler).
# "input" é o evento que a Lambda receberá — contém:
# - type: "movie" (informa qual tipo de mídia processar)
# - only_discover: true (processa APENAS o discover, pula gêneros/configurações)
# - database/tables: nomes das tabelas no Glue Catalog para registrar os dados
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

# Vincula a regra de séries à Lambda com payload para TV
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

# Permissão explícita para o EventBridge invocar a Lambda.
# Sem esta permissão, o EventBridge dispararia e receberia um erro de autorização.
# "principal = events.amazonaws.com" = o serviço EventBridge (não um usuário)
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

# =============================================================================
# REGRAS MENSAIS — Payload Completo (Gêneros + Configurações + Watch Providers Ref)
# =============================================================================
# Além do discover, atualiza tabelas de referência que mudam raramente:
# - genre_movie/tv: lista de gêneros (Ação, Comédia, Drama, etc.)
# - configuration_languages/countries: idiomas e países suportados pela TMDB
# - watch_providers_ref: lista de plataformas de streaming disponíveis
#
# Rodam todo dia 1 do mês — cadência suficiente para dados que mudam algumas vezes por ano.
# "skip_discover: true" = pula o discover nesta execução (já rodou na diária)
# =============================================================================

resource "aws_cloudwatch_event_rule" "lambda_api_movie_monthly" {
  name                = "lambda-api-movie-monthly-${var.env}"
  description         = "Dispara a Lambda para filmes com payload completo (mensal, dia 1)"
  schedule_expression = "cron(00 12 1 * ? *)" # Todo dia 1 do mês às 12:00 UTC / 09:00 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv_monthly" {
  name                = "lambda-api-tv-monthly-${var.env}"
  description         = "Dispara a Lambda para series com payload completo (mensal, dia 1)"
  schedule_expression = "cron(05 12 1 * ? *)" # Todo dia 1 do mês às 12:05 UTC / 09:05 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_target" "lambda_api_movie_monthly_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_monthly.name
  target_id = "lambda-api-movie-monthly"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                            = "movie",
    skip_discover                   = true, # Pula o discover (já rodou na execução diária)
    database                        = var.glue_catalog_database_movie_name,
    database_unified                = var.glue_catalog_database_unified_name,
    table_discover_movie            = var.glue_catalog_table_discover_movie_name,
    table_genre_movie               = var.glue_catalog_table_genre_movie_name,
    table_configuration_languages   = var.glue_catalog_table_configuration_languages_name,
    table_watch_providers_ref_movie = var.glue_catalog_table_watch_providers_ref_movie_name
  })
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_monthly_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv_monthly.name
  target_id = "lambda-api-tv-monthly"
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

resource "aws_lambda_permission" "allow_eventbridge_movie_monthly" {
  statement_id  = "AllowEventBridgeMovieMonthlyExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movie_monthly.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv_monthly" {
  statement_id  = "AllowEventBridgeTvMonthlyExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv_monthly.arn
}
