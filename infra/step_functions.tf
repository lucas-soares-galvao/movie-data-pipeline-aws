# =============================================================================
# step_functions.tf — State Machine de Backfill Histórico TMDB
# =============================================================================
# Orquestra invocações da Lambda uma vez por ano, do start_year até o ano atual.
# Resolve o timeout de 15 min da Lambda ao coletar muitos anos de uma vez.
#
# Como usar (console AWS ou CLI):
#   Step Functions → tmdb-sfn-backfill-{env} → Start Execution
#   Input: { "start_year": 2000 }
#
# end_year é calculado automaticamente como (ano da execução - 2).
# =============================================================================

# =============================================================================
# STATE MACHINE — Backfill Histórico
# =============================================================================
#
# Fluxo:
#   GenerateYears  → extrai end_year do timestamp de execução menos 2 (ex: "2027-01-01..." → 2025)
#   ComputeYears   → gera array [start_year, ..., end_year] via States.ArrayRange
#   ProcessEachYear → Map (MaxConcurrency=1): para cada ano, invoca movie depois tv
#
# Por que dois estados Pass (GenerateYears + ComputeYears)?
# States.ArrayRange exige inteiros. States.StringSplit retorna string, então
# States.StringToJson converte "2026" → 2026 no primeiro estado; o segundo
# usa o inteiro resultante em States.ArrayRange.
# =============================================================================

resource "aws_sfn_state_machine" "backfill" {
  name     = "${local.tmdb_prefix}-sfn-backfill-${var.env}"
  role_arn = aws_iam_role.sfn_backfill_role.arn

  definition = jsonencode({
    Comment = "Coleta TMDB discover ano a ano, invocando a Lambda uma vez por ano"
    StartAt = "GenerateYears"
    States = {

      # Extrai o ano da execução, converte para inteiro e subtrai 2.
      # $$.Execution.StartTime = "2027-01-01T00:00:00Z"
      # StringSplit por '-' → ["2027", "01", "01T00:00:00Z"]
      # ArrayGetItem(..., 0) → "2027"
      # StringToJson("2027") → 2027
      # MathAdd(2027, -2) → 2025
      GenerateYears = {
        Type = "Pass"
        Parameters = {
          "start_year.$" = "$.start_year"
          "end_year.$"   = "States.MathAdd(States.StringToJson(States.ArrayGetItem(States.StringSplit($$.Execution.StartTime, '-'), 0)), -2)"
        }
        Next = "ComputeYears"
      }

      ComputeYears = {
        Type = "Pass"
        Parameters = {
          "years.$" = "States.ArrayRange($.start_year, $.end_year, 1)"
        }
        Next = "ProcessEachYear"
      }

      ProcessEachYear = {
        Type           = "Map"
        ItemsPath      = "$.years"
        MaxConcurrency = 1
        Iterator = {
          StartAt = "InvokeLambdaMovie"
          States = {

            InvokeLambdaMovie = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                FunctionName = aws_lambda_function.simple_lambda.arn
                Payload = {
                  type                            = "movie"
                  only_discover                   = true
                  "start_year.$"                  = "$"
                  "end_year.$"                    = "$"
                  database                        = local.envs.glue_catalog_db_movie
                  database_unified                = local.envs.glue_catalog_db_unified
                  table_discover_movie            = local.envs.glue_catalog_tb_discover_movie
                  table_genre_movie               = local.envs.glue_catalog_tb_genre_movie
                  table_configuration_languages   = local.envs.glue_catalog_tb_configuration_languages
                  table_watch_providers_ref_movie = local.envs.glue_catalog_tb_watch_providers_ref_movie
                }
              }
              ResultPath = null
              Retry = [{
                ErrorEquals     = ["States.ALL"]
                MaxAttempts     = 2
                IntervalSeconds = 30
                BackoffRate     = 2
              }]
              Next = "InvokeLambdaTV"
            }

            InvokeLambdaTV = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                FunctionName = aws_lambda_function.simple_lambda.arn
                Payload = {
                  type                          = "tv"
                  only_discover                 = true
                  "start_year.$"                = "$"
                  "end_year.$"                  = "$"
                  database                      = local.envs.glue_catalog_db_tv
                  database_unified              = local.envs.glue_catalog_db_unified
                  table_discover_tv             = local.envs.glue_catalog_tb_discover_tv
                  table_genre_tv                = local.envs.glue_catalog_tb_genre_tv
                  table_configuration_countries = local.envs.glue_catalog_tb_configuration_countries
                  table_watch_providers_ref_tv  = local.envs.glue_catalog_tb_watch_providers_ref_tv
                }
              }
              ResultPath = null
              Retry = [{
                ErrorEquals     = ["States.ALL"]
                MaxAttempts     = 2
                IntervalSeconds = 30
                BackoffRate     = 2
              }]
              End = true
            }
          }
        }
        End = true
      }
    }
  })

  tags = local.component_tags.sfn_backfill

  depends_on = [
    aws_iam_role_policy.sfn_invoke_lambda,
    aws_lambda_function.simple_lambda
  ]
}
