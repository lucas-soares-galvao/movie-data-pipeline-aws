# =============================================================================
# eventbridge_lambda_api.tf — Agendamento automático da Lambda
#
# Estratégia: diária (só discover) + mensal (referências: gêneros, países, etc.)
# DESABILITADO em dev (local.eventbridge_schedule_state = "DISABLED") — invoque a Lambda manualmente.
# =============================================================================

# =============================================================================
# REGRAS DIÁRIAS — Apenas Discover (Descoberta de Novos Títulos)
# =============================================================================
# Discover = busca na API TMDB os filmes/séries mais populares.
# Roda diariamente para capturar novos lançamentos e atualizações de popularidade.
#
# Horários separados (10:00 e 10:05 UTC) para não disparar duas Lambdas
# simultaneamente — evita concorrência desnecessária nas chamadas à API TMDB.
# =============================================================================

# Agenda diária para discover de FILMES — 07:00 horário de Brasília (10:00 UTC)
resource "aws_cloudwatch_event_rule" "lambda_api_movie_daily" {
  name                = "${local.tmdb_prefix}-lambda-api-movie-daily-${var.env}"
  description         = "Dispara a Lambda para filmes com payload completo (diário)"
  schedule_expression = "cron(00 10 * * ? *)" # Todos os dias às 10:00 UTC / 07:00 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

# Agenda diária para discover de SÉRIES — 07:05 horário de Brasília (10:05 UTC)
resource "aws_cloudwatch_event_rule" "lambda_api_tv_daily" {
  name                = "${local.tmdb_prefix}-lambda-api-tv-daily-${var.env}"
  description         = "Dispara a Lambda para séries com payload completo (diário)"
  schedule_expression = "cron(05 10 * * ? *)" # Todos os dias às 10:05 UTC / 07:05 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

# Vincula a regra de filmes à Lambda e define o payload (JSON enviado ao handler).
# "input" é o evento que a Lambda receberá — contém:
# - type: "movie" (informa qual tipo de mídia processar)
# - only_discover: true (processa APENAS o discover, pula gêneros/configurações)
# - database/tables: nomes das tabelas no Glue Catalog para registrar os dados
resource "aws_cloudwatch_event_target" "lambda_api_movie_discover_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_daily.name
  target_id = "lambda-api-movie-discover"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                            = "movie",
    only_discover                   = true,
    database                        = local.envs.glue_catalog_db_movie,
    database_unified                = local.envs.glue_catalog_db_unified,
    table_discover_movie            = local.envs.glue_catalog_tb_discover_movie,
    table_genre_movie               = local.envs.glue_catalog_tb_genre_movie,
    table_configuration_languages   = local.envs.glue_catalog_tb_configuration_languages,
    table_watch_providers_ref_movie = local.envs.glue_catalog_tb_watch_providers_ref_movie,
    table_now_playing_movie         = local.envs.glue_catalog_tb_now_playing_movie
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}

# Vincula a regra de séries à Lambda com payload para TV
resource "aws_cloudwatch_event_target" "lambda_api_tv_discover_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv_daily.name
  target_id = "lambda-api-tv-discover"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                          = "tv",
    only_discover                 = true,
    database                      = local.envs.glue_catalog_db_tv,
    database_unified              = local.envs.glue_catalog_db_unified,
    table_discover_tv             = local.envs.glue_catalog_tb_discover_tv,
    table_genre_tv                = local.envs.glue_catalog_tb_genre_tv,
    table_configuration_countries = local.envs.glue_catalog_tb_configuration_countries,
    table_watch_providers_ref_tv  = local.envs.glue_catalog_tb_watch_providers_ref_tv
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}

# Permissão explícita para o EventBridge invocar a Lambda.
# Sem esta permissão, o EventBridge dispararia e receberia um erro de autorização.
# "principal = events.amazonaws.com" = o serviço EventBridge (não um usuário)
resource "aws_lambda_permission" "allow_eventbridge_movie_daily" {
  statement_id  = "AllowEventBridgeMovieDiscoverExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movie_daily.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv_daily" {
  statement_id  = "AllowEventBridgeTvDiscoverExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv_daily.arn
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
# "skip_daily: true" = pula o discover nesta execução (já rodou na diária)
# =============================================================================

resource "aws_cloudwatch_event_rule" "lambda_api_movie_monthly" {
  name                = "${local.tmdb_prefix}-lambda-api-movie-monthly-${var.env}"
  description         = "Dispara a Lambda para filmes com payload completo (mensal, dia 1)"
  schedule_expression = "cron(00 10 1 * ? *)" # Todo dia 1 do mês às 10:00 UTC / 07:00 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv_monthly" {
  name                = "${local.tmdb_prefix}-lambda-api-tv-monthly-${var.env}"
  description         = "Dispara a Lambda para series com payload completo (mensal, dia 1)"
  schedule_expression = "cron(05 10 1 * ? *)" # Todo dia 1 do mês às 10:05 UTC / 07:05 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_target" "lambda_api_movie_monthly_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_monthly.name
  target_id = "lambda-api-movie-monthly"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                            = "movie",
    skip_daily                      = true, # Pula o discover (já rodou na execução diária)
    database                        = local.envs.glue_catalog_db_movie,
    database_unified                = local.envs.glue_catalog_db_unified,
    table_discover_movie            = local.envs.glue_catalog_tb_discover_movie,
    table_genre_movie               = local.envs.glue_catalog_tb_genre_movie,
    table_configuration_languages   = local.envs.glue_catalog_tb_configuration_languages,
    table_watch_providers_ref_movie = local.envs.glue_catalog_tb_watch_providers_ref_movie
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_monthly_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv_monthly.name
  target_id = "lambda-api-tv-monthly"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                          = "tv",
    skip_daily                    = true,
    database                      = local.envs.glue_catalog_db_tv,
    database_unified              = local.envs.glue_catalog_db_unified,
    table_discover_tv             = local.envs.glue_catalog_tb_discover_tv,
    table_genre_tv                = local.envs.glue_catalog_tb_genre_tv,
    table_configuration_countries = local.envs.glue_catalog_tb_configuration_countries,
    table_watch_providers_ref_tv  = local.envs.glue_catalog_tb_watch_providers_ref_tv
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
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

# =============================================================================
# REGRA ANUAL — Backfill Histórico via Step Functions (1º de Janeiro)
# =============================================================================
# Roda o backfill completo uma vez por ano para incorporar o novo ano e
# manter a base histórica atualizada.
# Mesmo estado das demais regras (DISABLED em dev).
# =============================================================================

resource "aws_cloudwatch_event_rule" "sfn_backfill_annual" {
  name        = "${local.tmdb_prefix}-sfn-backfill-annual-${var.env}"
  description = "Dispara o backfill histórico TMDB todo dia 1 de janeiro"
  # schedule_expression = "cron(30 10 1 1 ? *)" # 1º de janeiro às 10:30 UTC / 07:30 BRT
  schedule_expression = "cron(30 20 * * ? *)" # 1º de janeiro às 10:00 UTC / 07:00 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.sfn_backfill
}

resource "aws_cloudwatch_event_target" "sfn_backfill_annual_target" {
  rule      = aws_cloudwatch_event_rule.sfn_backfill_annual.name
  target_id = "sfn-backfill-annual"
  arn       = aws_sfn_state_machine.backfill.arn
  role_arn  = aws_iam_role.eventbridge_sfn_role.arn

  input = jsonencode({
    start_year = 2022
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}
