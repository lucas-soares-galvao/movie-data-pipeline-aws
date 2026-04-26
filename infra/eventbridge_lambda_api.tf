# Regras EventBridge para acionar a Lambda com diferentes tipos

resource "aws_cloudwatch_event_rule" "lambda_api_movies" {
  name        = "lambda-api-movies"
  description = "Dispara a lambda para movies"
  schedule_expression = "cron(0 3 * * ? *)" # Exemplo: todo dia às 3h UTC
}

resource "aws_cloudwatch_event_rule" "lambda_api_tv" {
  name        = "lambda-api-tv"
  description = "Dispara a lambda para tv"
  schedule_expression = "cron(0 4 * * ? *)" # Exemplo: todo dia às 4h UTC
}

resource "aws_cloudwatch_event_target" "lambda_api_movies_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_movies.name
  target_id = "lambda-api-movies"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    tipo = "movie"
  })
}

resource "aws_cloudwatch_event_target" "lambda_api_tv_target" {
  rule      = aws_cloudwatch_event_rule.lambda_api_tv.name
  target_id = "lambda-api-tv"
  arn       = aws_lambda_function.simple_lambda.arn

  input = jsonencode({
    tipo = "tv"
  })
}

resource "aws_lambda_permission" "allow_eventbridge_movies" {
  statement_id  = "AllowExecutionFromEventBridgeMovies"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_movies.arn
}

resource "aws_lambda_permission" "allow_eventbridge_tv" {
  statement_id  = "AllowExecutionFromEventBridgeTV"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.simple_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_api_tv.arn
}
