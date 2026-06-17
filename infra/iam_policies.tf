# =============================================================================
# LAMBDA — Políticas da função Lambda
# =============================================================================

# Permite que a Lambda dispare e monitore os jobs Glue ETL e AGG.
# Resource restrito aos ARNs dos jobs especificos para limitar o escopo de acesso.
resource "aws_iam_role_policy" "lambda_start_glue_jobs" {
  name = "${local.tmdb_prefix}-lambda-api-start-glue-jobs-${var.env}"
  role = aws_iam_role.lambda_function.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["glue:StartJobRun", "glue:GetJobRun"]
      Resource = [
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:job/${local.envs.glue_etl_job_name}",
        "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:job/${local.envs.glue_agg_job_name}"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "lambda_s3_policy" {
  name = "${local.tmdb_prefix}-lambda-api-s3-policy-${var.env}"
  role = aws_iam_role.lambda_function.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:PutObject", "s3:GetObject"]
      Resource = [
        "arn:aws:s3:::${local.envs.s3_bucket_sor}/*",
        "arn:aws:s3:::${local.envs.s3_bucket_aux}/lambda_api/erro/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "lambda_secrets_manager_policy" {
  name = "${local.tmdb_prefix}-lambda-api-secrets-manager-${var.env}"
  role = aws_iam_role.lambda_function.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = var.tmdb_secret_arn
    }]
  })
}

# =============================================================================
# GLUE COMPARTILHADO — Leitura do código no bucket AUX (todos os jobs Glue)
# =============================================================================

# IMPORTANTE: O nome inclui o ambiente (${var.env}) para evitar conflito
# quando dev e prod sao provisionados na mesma conta AWS.
# Nomes de IAM Policy sao unicos por conta, entao sem sufixo haveria erro.
resource "aws_iam_policy" "glue_shared_read_code" {
  name = "${local.tmdb_prefix}-glue-shared-read-code-${var.env}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_aux}"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_aux}/*"]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "glue_etl_read_code" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}

resource "aws_iam_role_policy_attachment" "glue_dq_read_code" {
  role       = aws_iam_role.glue_dq_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}

# =============================================================================
# GLUE ETL — Políticas do job de transformação (SOR → SOT)
# =============================================================================

resource "aws_iam_role_policy" "glue_etl_logs" {
  name = "${local.tmdb_prefix}-glue-etl-logs-${var.env}"
  role = aws_iam_role.glue_etl_role.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteCustomGlueLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = [
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_etl_job_name}/*",
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_etl_job_name}/*:log-stream:*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_dq_logs" {
  name = "${local.tmdb_prefix}-glue-dq-logs-${var.env}"
  role = aws_iam_role.glue_dq_role.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteCustomGlueLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = [
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_data_quality_job_name}/*",
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_data_quality_job_name}/*:log-stream:*"
        ]
      }
    ]
  })
}
resource "aws_iam_role_policy" "glue_etl_sor_sot" {
  name = "${local.tmdb_prefix}-glue-etl-sor-sot-${var.env}"
  role = aws_iam_role.glue_etl_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_sor}",
          "arn:aws:s3:::${local.envs.s3_bucket_sot}"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sor}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}/*"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_etl_catalog" {
  name = "${local.tmdb_prefix}-glue-etl-catalog-${var.env}"
  role = aws_iam_role.glue_etl_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadCatalog"
        Effect = "Allow"
        Action = [
          "glue:GetTable",
          "glue:GetPartitions",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_movie_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_tv_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_movie_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_tv_name}/*",
        ]
      },
      {
        Sid    = "WriteSOTTable"
        Effect = "Allow"
        Action = [
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:CreatePartition",
          "glue:BatchCreatePartition",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_movie_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_tv_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_movie_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_tv_name}/*",
        ]
      }
    ]
  })
}

# Permite que o Glue ETL inicie o job de Data Quality ao final do processamento.
resource "aws_iam_role_policy" "glue_etl_start_dq" {
  name = "${local.tmdb_prefix}-glue-etl-start-dq-${var.env}"
  role = aws_iam_role.glue_etl_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["glue:StartJobRun"]
      Resource = ["arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:job/${local.envs.glue_data_quality_job_name}"]
    }]
  })
}

# Permite que o Glue ETL inicie o job Details ao final do run tv + discover.
resource "aws_iam_role_policy" "glue_etl_start_details" {
  name = "${local.tmdb_prefix}-glue-etl-start-details-${var.env}"
  role = aws_iam_role.glue_etl_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["glue:StartJobRun"]
      Resource = ["arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:job/${local.envs.glue_details_job_name}"]
    }]
  })
}

# =============================================================================
# GLUE DQ — Políticas do job de qualidade de dados
# =============================================================================

resource "aws_iam_role_policy" "glue_dq_read_sot_spec" {
  name = "${local.tmdb_prefix}-glue-dq-read-sot-spec-${var.env}"
  role = aws_iam_role.glue_dq_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_sot}",
          "arn:aws:s3:::${local.envs.s3_bucket_spec}",
        ]
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/*",
          "arn:aws:s3:::${local.envs.s3_bucket_spec}/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_dq_write_results" {
  name = "${local.tmdb_prefix}-glue-dq-write-results-${var.env}"
  role = aws_iam_role.glue_dq_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = [
        "arn:aws:s3:::${local.envs.s3_bucket_data_quality}",
        "arn:aws:s3:::${local.envs.s3_bucket_data_quality}/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "glue_dq_catalog" {
  name = "${local.tmdb_prefix}-glue-dq-catalog-${var.env}"
  role = aws_iam_role.glue_dq_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadCatalog"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_movie_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_tv_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_unified_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_movie_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_tv_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_unified_name}/*",
        ]
      },
      {
        Sid    = "WriteResultsTable"
        Effect = "Allow"
        Action = [
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:CreatePartition",
          "glue:BatchCreatePartition",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_unified_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_unified_name}/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_dq_sns_publish" {
  name = "${local.tmdb_prefix}-glue-dq-sns-publish-${var.env}"
  role = aws_iam_role.glue_dq_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["sns:Publish"]
      Resource = [
        aws_sns_topic.glue_data_quality_failure_notifications.arn,
        aws_sns_topic.glue_data_quality_metrics_notifications.arn
      ]
    }]
  })
}

# =============================================================================
# SNS — Políticas de publicação dos tópicos (quem pode publicar em cada tópico)
# =============================================================================

data "aws_iam_policy_document" "glue_etl_failure_topic_policy" {
  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.glue_etl_failure_notifications.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.glue_etl_failed.arn]
    }
  }
}

resource "aws_sns_topic_policy" "glue_etl_failure_topic_policy" {
  arn    = aws_sns_topic.glue_etl_failure_notifications.arn
  policy = data.aws_iam_policy_document.glue_etl_failure_topic_policy.json
}

data "aws_iam_policy_document" "glue_data_quality_failure_topic_policy" {
  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.glue_data_quality_failure_notifications.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.glue_data_quality_failed.arn]
    }
  }

  statement {
    sid    = "AllowGlueDQRolePublish"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.glue_dq_role.arn]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.glue_data_quality_failure_notifications.arn]
  }
}

resource "aws_sns_topic_policy" "glue_data_quality_failure_topic_policy" {
  arn    = aws_sns_topic.glue_data_quality_failure_notifications.arn
  policy = data.aws_iam_policy_document.glue_data_quality_failure_topic_policy.json
}

data "aws_iam_policy_document" "glue_data_quality_metrics_topic_policy" {
  statement {
    sid    = "AllowGlueDQRolePublish"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.glue_dq_role.arn]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.glue_data_quality_metrics_notifications.arn]
  }
}

resource "aws_sns_topic_policy" "glue_data_quality_metrics_topic_policy" {
  arn    = aws_sns_topic.glue_data_quality_metrics_notifications.arn
  policy = data.aws_iam_policy_document.glue_data_quality_metrics_topic_policy.json
}

data "aws_iam_policy_document" "lambda_failure_topic_policy" {
  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.lambda_failure_notifications.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.lambda_alarm_failed_state_change.arn]
    }
  }
}

resource "aws_sns_topic_policy" "lambda_failure_topic_policy" {
  arn    = aws_sns_topic.lambda_failure_notifications.arn
  policy = data.aws_iam_policy_document.lambda_failure_topic_policy.json
}

data "aws_iam_policy_document" "eventbridge_failure_topic_policy" {
  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.eventbridge_failure_notifications.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.eventbridge_alarm_failed_state_change.arn]
    }
  }
}

resource "aws_sns_topic_policy" "eventbridge_failure_topic_policy" {
  arn    = aws_sns_topic.eventbridge_failure_notifications.arn
  policy = data.aws_iam_policy_document.eventbridge_failure_topic_policy.json
}

# =============================================================================
# GLUE AGG — Políticas do job de agregação (SOT → SPEC)
# =============================================================================

resource "aws_iam_role_policy" "glue_agg_logs" {
  name = "${local.tmdb_prefix}-glue-agg-logs-${var.env}"
  role = aws_iam_role.glue_agg_role.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteCustomGlueLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = [
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_agg_job_name}/*",
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_agg_job_name}/*:log-stream:*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_agg_s3" {
  name = "${local.tmdb_prefix}-glue-agg-s3-${var.env}"
  role = aws_iam_role.glue_agg_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_sot}",
          "arn:aws:s3:::${local.envs.s3_bucket_temp}",
          "arn:aws:s3:::${local.envs.s3_bucket_spec}"
        ]
      },
      {
        Sid      = "ReadSOTForAthena"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}/*"]
      },
      {
        Sid      = "AthenaTemp"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_temp}/${local.tmdb_prefix}/athena/glue_agg/*"]
      },
      {
        Sid      = "WriteSpec"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_spec}/*"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_agg_catalog" {
  name = "${local.tmdb_prefix}-glue-agg-catalog-${var.env}"
  role = aws_iam_role.glue_agg_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadCatalog"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_movie_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_tv_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_unified_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_movie_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_tv_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_unified_name}/*",
        ]
      },
      {
        Sid    = "WriteSpecTable"
        Effect = "Allow"
        Action = [
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:BatchCreatePartition",
          "glue:CreatePartition",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_unified_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_unified_name}/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_agg_athena" {
  name = "${local.tmdb_prefix}-glue-agg-athena-${var.env}"
  role = aws_iam_role.glue_agg_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:GetWorkGroup"
      ]
      Resource = "arn:aws:athena:sa-east-1:${data.aws_caller_identity.current.account_id}:workgroup/primary"
    }]
  })
}

data "aws_iam_policy_document" "glue_agg_success_topic_policy" {
  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.glue_agg_success_notifications.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.glue_agg_succeeded.arn]
    }
  }
}

resource "aws_sns_topic_policy" "glue_agg_success_topic_policy" {
  arn    = aws_sns_topic.glue_agg_success_notifications.arn
  policy = data.aws_iam_policy_document.glue_agg_success_topic_policy.json
}

data "aws_iam_policy_document" "glue_agg_failure_topic_policy" {
  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.glue_agg_failure_notifications.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.glue_agg_failed.arn]
    }
  }
}

resource "aws_sns_topic_policy" "glue_agg_failure_topic_policy" {
  arn    = aws_sns_topic.glue_agg_failure_notifications.arn
  policy = data.aws_iam_policy_document.glue_agg_failure_topic_policy.json
}

data "aws_iam_policy_document" "glue_details_failure_topic_policy" {
  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.glue_details_failure_notifications.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.glue_details_failed.arn]
    }
  }
}

resource "aws_sns_topic_policy" "glue_details_failure_topic_policy" {
  arn    = aws_sns_topic.glue_details_failure_notifications.arn
  policy = data.aws_iam_policy_document.glue_details_failure_topic_policy.json
}

# =============================================================================
# POLÍTICAS IAM — GLUE DETAILS
# =============================================================================

resource "aws_iam_role_policy" "glue_details_logs" {
  name = "${local.tmdb_prefix}-glue-details-logs-${var.env}"
  role = aws_iam_role.glue_details_role.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "WriteCustomGlueLogs"
      Effect = "Allow"
      Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = [
        "arn:aws:logs:*:*:log-group:/${local.envs.glue_details_job_name}/*",
        "arn:aws:logs:*:*:log-group:/${local.envs.glue_details_job_name}/*:log-stream:*"
      ]
    }]
  })
}

# Leitura do SOT (tabelas de discover via Athena) + escrita das tabelas de detalhe
resource "aws_iam_role_policy" "glue_details_s3" {
  name = "${local.tmdb_prefix}-glue-details-s3-${var.env}"
  role = aws_iam_role.glue_details_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_sot}",
          "arn:aws:s3:::${local.envs.s3_bucket_temp}"
        ]
      },
      {
        Sid      = "ReadSOTForAthena"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}/*"]
      },
      {
        Sid      = "AthenaTemp"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_temp}/${local.tmdb_prefix}/athena/glue_details/*"]
      },
      {
        Sid    = "WriteDetailsSOT"
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${var.glue_catalog_table_details_movie_name}/*",
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${var.glue_catalog_table_details_tv_name}/*",
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${var.glue_catalog_table_watch_providers_movie_name}/*",
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/${local.tmdb_prefix}/${var.glue_catalog_table_watch_providers_tv_name}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_details_catalog" {
  name = "${local.tmdb_prefix}-glue-details-catalog-${var.env}"
  role = aws_iam_role.glue_details_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadCatalog"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_movie_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_tv_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_movie_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_tv_name}/*",
        ]
      },
      {
        Sid    = "WriteDetailsTable"
        Effect = "Allow"
        Action = [
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:BatchCreatePartition",
          "glue:CreatePartition",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_movie_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_tv_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_movie_name}/*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_tv_name}/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_details_athena" {
  name = "${local.tmdb_prefix}-glue-details-athena-${var.env}"
  role = aws_iam_role.glue_details_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:GetWorkGroup"
      ]
      Resource = "arn:aws:athena:sa-east-1:${data.aws_caller_identity.current.account_id}:workgroup/primary"
    }]
  })
}

resource "aws_iam_role_policy" "glue_details_secrets" {
  name = "${local.tmdb_prefix}-glue-details-secrets-${var.env}"
  role = aws_iam_role.glue_details_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = var.tmdb_secret_arn
    }]
  })
}

resource "aws_iam_role_policy" "glue_details_start_agg" {
  name = "${local.tmdb_prefix}-glue-details-start-agg-${var.env}"
  role = aws_iam_role.glue_details_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["glue:StartJobRun"]
      Resource = ["arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:job/${local.envs.glue_agg_job_name}"]
    }]
  })
}

resource "aws_iam_role_policy" "glue_details_start_dq" {
  name = "${local.tmdb_prefix}-glue-details-start-dq-${var.env}"
  role = aws_iam_role.glue_details_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["glue:StartJobRun"]
      Resource = ["arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:job/${local.envs.glue_data_quality_job_name}"]
    }]
  })
}

# =============================================================================
# STEP FUNCTIONS — Políticas do backfill histórico
# =============================================================================

resource "aws_iam_role_policy" "sfn_invoke_lambda" {
  name = "${local.tmdb_prefix}-sfn-backfill-invoke-lambda-${var.env}"
  role = aws_iam_role.sfn_backfill_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "InvokeTmdbLambda"
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.simple_lambda.arn
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_start_sfn" {
  name = "${local.tmdb_prefix}-eventbridge-start-sfn-${var.env}"
  role = aws_iam_role.eventbridge_sfn_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "StartBackfillExecution"
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.backfill.arn
    }]
  })
}

