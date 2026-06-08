# Raciocinio: concentra politicas minimas necessarias para Lambda/Glue acessarem servicos AWS.

# Permite que a Lambda dispare e monitore os jobs Glue ETL e AGG.
# Resource restrito aos ARNs dos jobs especificos para limitar o escopo de acesso.
resource "aws_iam_role_policy" "lambda_start_glue_jobs" {
  name = "${local.envs.lambda_api_name}-start-glue-jobs"
  role = aws_iam_role.lambda_function.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["glue:StartJobRun", "glue:GetJobRun"]
      Resource = [
        "arn:aws:glue:*:*:job/${local.envs.glue_etl_job_name}",
        "arn:aws:glue:*:*:job/${local.envs.glue_agg_job_name}"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "lambda_s3_policy" {
  name = "${local.envs.lambda_api_name}-s3-policy"
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
  name = "${local.envs.lambda_api_name}-secrets-manager"
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

# =========================
# READ CODE (AMBOS)
# =========================
# IMPORTANTE: O nome inclui o ambiente (${var.env}) para evitar conflito
# quando dev e prod sao provisionados na mesma conta AWS.
# Nomes de IAM Policy sao unicos por conta, entao sem sufixo haveria erro.
resource "aws_iam_policy" "glue_shared_read_code" {
  name = "glue-shared-read-code-${var.env}"

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

# attach nas duas roles
resource "aws_iam_role_policy_attachment" "glue_etl_read_code" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}

resource "aws_iam_role_policy_attachment" "glue_dq_read_code" {
  role       = aws_iam_role.glue_dq_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}

resource "aws_iam_role_policy" "glue_etl_logs" {
  name = "glue-etl-logs"
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
  name = "glue-dq-logs"
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
# =========================
# ETL - SOR → SOT
# =========================
resource "aws_iam_role_policy" "glue_etl_sor_sot" {
  name = "glue-etl-sor-sot"
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

# =========================
# ETL - Glue Catalog
# =========================
resource "aws_iam_role_policy" "glue_etl_catalog" {
  name = "glue-etl-catalog"
  role = aws_iam_role.glue_etl_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "glue:GetTable",
        "glue:CreateTable",
        "glue:UpdateTable",
        "glue:GetPartitions",
        "glue:CreatePartition"
      ]
      Resource = "*"
    }]
  })
}

# =========================
# ETL - Start DQ Job
# =========================
# Permite que o Glue ETL inicie o job de Data Quality ao final do processamento.
resource "aws_iam_role_policy" "glue_etl_start_dq" {
  name = "glue-etl-start-dq"
  role = aws_iam_role.glue_etl_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["glue:StartJobRun"]
      Resource = ["arn:aws:glue:*:*:job/${local.envs.glue_data_quality_job_name}"]
    }]
  })
}

# =========================
# ETL - Start Details Job
# =========================
# Permite que o Glue ETL inicie o job Details ao final do run tv + discover.
resource "aws_iam_role_policy" "glue_etl_start_details" {
  name = "glue-etl-start-details"
  role = aws_iam_role.glue_etl_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["glue:StartJobRun"]
      Resource = ["arn:aws:glue:*:*:job/${local.envs.glue_details_job_name}"]
    }]
  })
}

# =========================
# DQ - Read SOT
# =========================
resource "aws_iam_role_policy" "glue_dq_read_sot" {
  name = "glue-dq-read-sot"
  role = aws_iam_role.glue_dq_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}/*"]
      }
    ]
  })
}

# =========================
# DQ - Write results
# =========================
resource "aws_iam_role_policy" "glue_dq_write_results" {
  name = "glue-dq-write-results"
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

# =========================
# DQ - SNS Publish (notificação de métrica Failed)
# =========================
resource "aws_iam_role_policy" "glue_dq_sns_publish" {
  name = "glue-dq-sns-publish"
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

# =========================
# SNS TOPIC POLICIES
# =========================
data "aws_caller_identity" "current" {}

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

# =========================
# AGG - Logs
# =========================
resource "aws_iam_role_policy" "glue_agg_logs" {
  name = "glue-agg-logs"
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

# =========================
# AGG - S3 (SOT leitura Athena + TEMP + SPEC escrita)
# =========================
resource "aws_iam_role_policy" "glue_agg_s3" {
  name = "glue-agg-s3"
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
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_temp}/athena/glue_agg/*"]
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

# =========================
# AGG - Glue Catalog (leitura SOT + escrita SPEC)
# =========================
resource "aws_iam_role_policy" "glue_agg_catalog" {
  name = "glue-agg-catalog"
  role = aws_iam_role.glue_agg_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "glue:GetDatabase",
        "glue:GetTable",
        "glue:CreateTable",
        "glue:UpdateTable",
        "glue:GetPartitions",
        "glue:BatchCreatePartition",
        "glue:CreatePartition"
      ]
      Resource = "*"
    }]
  })
}

# =========================
# AGG - Athena
# =========================
resource "aws_iam_role_policy" "glue_agg_athena" {
  name = "glue-agg-athena"
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
      Resource = "*"
    }]
  })
}

# =========================
# AGG - SNS Topic Policies
# =========================
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

