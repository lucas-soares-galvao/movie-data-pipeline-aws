# Raciocinio: agenda invocacoes da Lambda por tipo de midia para ingestao recorrente automatica.

resource "aws_cloudwatch_event_rule" "lambda_api_movie" {
  name        = "lambda-api-movie-${var.env}"
  description = "Dispara a Lambda para filmes"
  schedule_expression = "cron(30 01 * * ? *)" # Todos os dias as 01:30 UTC
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv" {
  name        = "lambda-api-tv-${var.env}"
  description = "Dispara a Lambda para series"
  schedule_expression = "cron(45 01 * * ? *)" # Todos os dias as 01:45 UTC
}

resource "aws_cloudwatch_event_target" "lambda_api_movie_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movie.name
  target_id = "lambda-api-movie"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type = "movie",
    database = var.glue_catalog_database_name,
    table_discover_movie = var.glue_catalog_table_discover_movie_name,
    table_genre_movie = var.glue_catalog_table_genre_movie_name,
    table_configuration_languages = var.glue_catalog_table_configuration_languages_name
  })
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv.name
  target_id = "lambda-api-tv"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type = "tv",
    database = var.glue_catalog_database_name,
    table_discover_tv = var.glue_catalog_table_discover_tv_name,
    table_genre_tv = var.glue_catalog_table_genre_tv_name,
    table_configuration_countries = var.glue_catalog_table_configuration_countries_name
  })
}

resource "aws_lambda_permission" "allow_eventbridge_movie" {
  statement_id  = "AllowEventBridgemovieExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movie.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv" {
  statement_id  = "AllowEventBridgetvExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv.arn
}
