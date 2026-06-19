# =============================================================================
# step_functions.tf — State Machine de Backfill Histórico TMDB
# =============================================================================
# Orquestra invocações da Lambda em lotes de 2 anos, do start_year até o ano atual.
# Resolve o timeout de 15 min da Lambda e evita estourar max_concurrent_runs do Glue.
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
#   GenerateYears   → extrai end_year do timestamp de execução menos 2
#   ComputeYears    → gera array [start_year, ..., end_year]
#   CreateBatches   → divide array em sub-arrays de 2 anos via States.ArrayPartition
#   ProcessBatches  → Map (MaxConcurrency=1): para cada batch:
#                     InvokeLambdaMovie → Wait 5min → InvokeLambdaTV → Wait 5min
#
# O intervalo de 5 min entre movie/tv e entre batches segue o mesmo padrão do
# EventBridge diário e garante que os Glue Details (~4min) terminem antes do
# próximo batch iniciar, evitando estourar max_concurrent_runs.
#
# A Lambda recebe:
#   - start_year / loop_end_year: limites do loop (ex: 2000, 2001)
#   - end_year: último ano do backfill inteiro (ex: 2025)
# Isso garante que o Glue AGG só dispare no último ano do último batch.
# =============================================================================

resource "aws_sfn_state_machine" "backfill" {
  name     = "${local.tmdb_prefix}-sfn-backfill-${var.env}"
  role_arn = aws_iam_role.sfn_backfill_role.arn

  definition = jsonencode({
    Comment = "Coleta TMDB discover em lotes de 2 anos, com 5 min entre movie/tv e entre batches"
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

      # Gera o array [start_year, ..., end_year].
      # States.ArrayRange exige inteiros — por isso o estado anterior converte a string.
      ComputeYears = {
        Type = "Pass"
        Parameters = {
          "years.$"    = "States.ArrayRange($.start_year, $.end_year, 1)"
          "end_year.$" = "$.end_year"
        }
        Next = "CreateBatches"
      }

      # Divide o array de anos em sub-arrays de 2 elementos.
      # Ex: [2000,2001,2002,2003,2004] → [[2000,2001],[2002,2003],[2004]]
      # O último batch pode ter 1 ano se o total for ímpar.
      CreateBatches = {
        Type = "Pass"
        Parameters = {
          "batches.$"  = "States.ArrayPartition($.years, 2)"
          "end_year.$" = "$.end_year"
        }
        Next = "ProcessBatches"
      }

      # Itera sobre cada batch sequencialmente (MaxConcurrency=1).
      # ItemSelector injeta o batch e o end_year global em cada iteração.
      ProcessBatches = {
        Type           = "Map"
        ItemsPath      = "$.batches"
        MaxConcurrency = 1
        ItemSelector = {
          "batch.$"    = "$$.Map.Item.Value"
          "end_year.$" = "$.end_year"
        }
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
                  "start_year.$"                  = "States.ArrayGetItem($.batch, 0)"
                  "loop_end_year.$"               = "States.ArrayGetItem($.batch, States.MathAdd(States.ArrayLength($.batch), -1))"
                  "end_year.$"                    = "$.end_year"
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
              Next = "WaitBeforeTV"
            }

            WaitBeforeTV = {
              Type    = "Wait"
              Seconds = 300
              Next    = "InvokeLambdaTV"
            }

            InvokeLambdaTV = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                FunctionName = aws_lambda_function.simple_lambda.arn
                Payload = {
                  type                          = "tv"
                  only_discover                 = true
                  "start_year.$"                = "States.ArrayGetItem($.batch, 0)"
                  "loop_end_year.$"             = "States.ArrayGetItem($.batch, States.MathAdd(States.ArrayLength($.batch), -1))"
                  "end_year.$"                  = "$.end_year"
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
              Next = "WaitBeforeNextBatch"
            }

            WaitBeforeNextBatch = {
              Type    = "Wait"
              Seconds = 300
              End     = true
            }
          }
        }
        End = true
      }
    }
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_backfill.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = local.component_tags.sfn_backfill

  depends_on = [
    aws_iam_role_policy.sfn_invoke_lambda,
    aws_iam_role_policy.sfn_backfill_logs,
    aws_lambda_function.simple_lambda,
    aws_cloudwatch_log_group.sfn_backfill
  ]
}
