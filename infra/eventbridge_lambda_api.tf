# EventBridge rules to trigger Lambda with different types

resource "aws_cloudwatch_event_rule" "lambda_api_movies" {
  name        = "lambda-api-movies"
  description = "Triggers the lambda for movies"
  schedule_expression = "cron(0 15 * * ? *)" # Example: every day at 3pm UTC
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv" {
  name        = "lambda-api-tv"
  description = "Triggers the lambda for tv"
  schedule_expression = "cron(30 15 * * ? *)" # Example: every day at 3:30pm UTC
}

resource "aws_cloudwatch_event_target" "lambda_api_movies_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movies.name
  target_id = "lambda-api-movies"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type = "movie",
    database = var.glue_catalog_database_name,
    table_movies = var.glue_catalog_table_movies_name,
    table_genre_movie = var.glue_catalog_table_genre_movie_name
  })
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv.name
  target_id = "lambda-api-tv"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type = "tv",
    database = var.glue_catalog_database_name,
    table_tv = var.glue_catalog_table_tv_name,
    table_genre_tv = var.glue_catalog_table_genre_tv_name
  })
}

resource "aws_lambda_permission" "allow_eventbridge_movies" {
  statement_id  = "AllowEventBridgeMoviesExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movies.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv" {
  statement_id  = "AllowEventBridgetvExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv.arn
}
