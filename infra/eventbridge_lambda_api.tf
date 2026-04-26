# EventBridge rules to trigger Lambda with different types

resource "aws_cloudwatch_event_rule" "lambda_api_movies" {
  name        = "lambda-api-movies"
  description = "Triggers the lambda for movies"
  schedule_expression = "cron(0 3 * * ? *)" # Example: every day at 3am UTC
}

resource "aws_cloudwatch_event_rule" "lambda_api_series" {
  name        = "lambda-api-series"
  description = "Triggers the lambda for series"
  schedule_expression = "cron(0 4 * * ? *)" # Example: every day at 4am UTC
}

resource "aws_cloudwatch_event_target" "lambda_api_movies_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movies.name
  target_id = "lambda-api-movies"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type = "movie"
  })
}

resource "aws_cloudwatch_event_target" "lambda_api_series_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_series.name
  target_id = "lambda-api-series"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    type = "series"
  })
}

resource "aws_lambda_permission" "allow_eventbridge_movies" {
  statement_id  = "AllowEventBridgeMoviesExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movies.arn
}

resource "aws_lambda_permission" "allow_eventbridge_series" {
  statement_id  = "AllowEventBridgeSeriesExecution"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_series.arn
}
