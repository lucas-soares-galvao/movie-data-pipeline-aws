# =============================================================================
# eventbridge_lambda_api.tf — Agendamento automático da Lambda
#
# Estratégia: semanal (só discover) + mensal (referências + discover do ano anterior)
# DESABILITADO em dev (local.eventbridge_schedule_state = "DISABLED") — invoque a Lambda manualmente.
# =============================================================================

# =============================================================================
# REGRAS SEMANAIS — Apenas Discover (Descoberta de Novos Títulos)
# =============================================================================
# Discover = busca na API TMDB os filmes/séries mais populares.
# Roda semanalmente (domingos) para capturar novos lançamentos e atualizações de popularidade.
#
# Horários separados (09:00 e 09:05 UTC) para não disparar duas Lambdas
# simultaneamente — evita concorrência desnecessária nas chamadas à API TMDB.
# Gap de 30 min entre semanal e mensal evita ConcurrentModificationException
# no Glue Catalog quando ambos tocam a mesma partição.
# =============================================================================

# Agenda semanal para discover de FILMES — domingos às 06:00 BRT (09:00 UTC)
resource "aws_cloudwatch_event_rule" "lambda_api_movie_weekly" {
  name                = "${local.tmdb_prefix}-lambda-api-movie-weekly-${var.env}"
  description         = "Dispara a Lambda para filmes com payload completo (semanal, domingos)"
  schedule_expression = "cron(00 09 ? * SUN *)" # Domingos às 09:00 UTC / 06:00 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

# Agenda semanal para discover de SÉRIES — domingos às 06:05 BRT (09:05 UTC)
resource "aws_cloudwatch_event_rule" "lambda_api_tv_weekly" {
  name                = "${local.tmdb_prefix}-lambda-api-tv-weekly-${var.env}"
  description         = "Dispara a Lambda para séries com payload completo (semanal, domingos)"
  schedule_expression = "cron(05 09 ? * SUN *)" # Domingos às 09:05 UTC / 06:05 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

# Vincula a regra de filmes à Lambda e define o payload (JSON enviado ao handler).
# "input" é o evento que a Lambda receberá — contém:
# - type: "movie" (informa qual tipo de mídia processar)
# - flags de controle (only_weekly_tables, only_monthly_tables, etc.) — ver app/lambda_api/main.py
# - database/tables: nomes das tabelas no Glue Catalog para registrar os dados
resource "aws_cloudwatch_event_target" "lambda_api_movie_discover_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_weekly.name
  target_id = "lambda-api-movie-discover"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                            = "movie",
    only_weekly_tables              = true,
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
  rule      = aws_cloudwatch_event_rule.lambda_api_tv_weekly.name
  target_id = "lambda-api-tv-discover"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                          = "tv",
    only_weekly_tables            = true,
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
resource "aws_lambda_permission" "allow_eventbridge_movie_weekly" {
  statement_id  = "AllowEventBridgeMovieDiscoverExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movie_weekly.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv_weekly" {
  statement_id  = "AllowEventBridgeTvDiscoverExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv_weekly.arn
}

# =============================================================================
# REGRAS SEMANAIS — Changes API do TMDB (Refresh de Títulos Já Catalogados)
# =============================================================================
# Fecha o gap de staleness em títulos de qualquer ano (não só ano atual/anterior):
# /movie/changes e /tv/changes retornam IDs que mudaram numa janela de data,
# independente do ano de lançamento. Só refresca títulos já existentes no
# catálogo (nunca expande via discover) — ver app/glue_details/src/utils.py.
#
# Cadência semanal (não diária) para economizar custo do Glue Details, que é
# acionado a cada execução. Mesmo horário do discover semanal (09:00/09:05 UTC),
# um dia antes (sábado) — um dia inteiro de folga evita que os dois ciclos de
# Glue Details concorram pelo rate limit do TMDB, sem precisar coordenar
# horários finos.
# =============================================================================

resource "aws_cloudwatch_event_rule" "lambda_api_movie_changes_weekly" {
  name                = "${local.tmdb_prefix}-lambda-api-movie-changes-weekly-${var.env}"
  description         = "Dispara a Lambda em modo changes para filmes (semanal, sábados)"
  schedule_expression = "cron(00 09 ? * SAT *)" # Sábados às 09:00 UTC / 06:00 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv_changes_weekly" {
  name                = "${local.tmdb_prefix}-lambda-api-tv-changes-weekly-${var.env}"
  description         = "Dispara a Lambda em modo changes para séries (semanal, sábados)"
  schedule_expression = "cron(05 09 ? * SAT *)" # Sábados às 09:05 UTC / 06:05 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_target" "lambda_api_movie_changes_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_changes_weekly.name
  target_id = "lambda-api-movie-changes"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                = "movie",
    only_changes_tables = true,
    database            = local.envs.glue_catalog_db_movie
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_changes_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv_changes_weekly.name
  target_id = "lambda-api-tv-changes"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                = "tv",
    only_changes_tables = true,
    database            = local.envs.glue_catalog_db_tv
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}

resource "aws_lambda_permission" "allow_eventbridge_movie_changes_weekly" {
  statement_id  = "AllowEventBridgeMovieChangesExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movie_changes_weekly.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv_changes_weekly" {
  statement_id  = "AllowEventBridgeTvChangesExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv_changes_weekly.arn
}

# =============================================================================
# REGRA SEMANAL — Rotation Refresh (Catálogo Antigo, Sábados)
# =============================================================================
# Fecha o gap de staleness que o /changes da TMDB não cobre (nem toda mudança
# real é reportada lá): força o refresh (FORCE_REFETCH=true) de 1 ano do
# catálogo antigo (2000 até current_year - 3) por execução, via um ponteiro
# simples em SSM Parameter Store (ver ssm.tf e only_rotation_refresh em
# app/lambda_api/main.py) — sem checkpoint de loop, sem ajuste manual de ano
# em ano. Ciclo completo em ~24 semanas.
#
# Mesmo dia do changes (sábado), 10 min depois (09:10/09:15 UTC) para não
# concorrer pelo rate limit do TMDB nem pelo max_concurrent_runs do Glue Data
# Quality, que ambos os fluxos acionam.
# =============================================================================

resource "aws_cloudwatch_event_rule" "lambda_api_movie_rotation_weekly" {
  name                = "${local.tmdb_prefix}-lambda-api-movie-rotation-weekly-${var.env}"
  description         = "Dispara a Lambda em modo rotation refresh para filmes (semanal, sábados)"
  schedule_expression = "cron(10 09 ? * SAT *)" # Sábados às 09:10 UTC / 06:10 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv_rotation_weekly" {
  name                = "${local.tmdb_prefix}-lambda-api-tv-rotation-weekly-${var.env}"
  description         = "Dispara a Lambda em modo rotation refresh para séries (semanal, sábados)"
  schedule_expression = "cron(15 09 ? * SAT *)" # Sábados às 09:15 UTC / 06:15 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_target" "lambda_api_movie_rotation_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_rotation_weekly.name
  target_id = "lambda-api-movie-rotation"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                  = "movie",
    only_rotation_refresh = true,
    database              = local.envs.glue_catalog_db_movie
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_rotation_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv_rotation_weekly.name
  target_id = "lambda-api-tv-rotation"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                  = "tv",
    only_rotation_refresh = true,
    database              = local.envs.glue_catalog_db_tv
  })

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}

resource "aws_lambda_permission" "allow_eventbridge_movie_rotation_weekly" {
  statement_id  = "AllowEventBridgeMovieRotationExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movie_rotation_weekly.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv_rotation_weekly" {
  statement_id  = "AllowEventBridgeTvRotationExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv_rotation_weekly.arn
}

# =============================================================================
# REGRAS MENSAIS — Referência + Discover do Ano Anterior
# =============================================================================
# Atualiza tabelas de referência que mudam raramente:
# - genre_movie/tv: lista de gêneros (Ação, Comédia, Drama, etc.)
# - configuration_languages/countries: idiomas e países suportados pela TMDB
# - watch_providers_ref: lista de plataformas de streaming disponíveis
#
# Além disso, roda o discover do ano anterior (current_year - 1) para manter
# popularidade e streaming providers atualizados sem custo diário/semanal.
#
# Rodam todo dia 1 do mês — cadência suficiente para dados estáveis.
# "only_monthly_tables: true" = referência + discover do ano passado, sem now_playing.
# =============================================================================

resource "aws_cloudwatch_event_rule" "lambda_api_movie_monthly" {
  name                = "${local.tmdb_prefix}-lambda-api-movie-monthly-${var.env}"
  description         = "Dispara a Lambda para filmes com payload completo (mensal, dia 1)"
  schedule_expression = "cron(30 09 1 * ? *)" # Todo dia 1 do mês às 09:30 UTC / 06:30 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv_monthly" {
  name                = "${local.tmdb_prefix}-lambda-api-tv-monthly-${var.env}"
  description         = "Dispara a Lambda para series com payload completo (mensal, dia 1)"
  schedule_expression = "cron(35 09 1 * ? *)" # Todo dia 1 do mês às 09:35 UTC / 06:35 BRT
  state               = local.eventbridge_schedule_state
  tags                = local.component_tags.eventbridge
}

resource "aws_cloudwatch_event_target" "lambda_api_movie_monthly_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie_monthly.name
  target_id = "lambda-api-movie-monthly"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type                            = "movie",
    only_monthly_tables             = true,
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
    only_monthly_tables           = true,
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
