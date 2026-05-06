# Custom IAM policies (Lambda and Glue)

resource "aws_iam_role_policy" "lambda_start_glue_jobs" {
  name = "${local.envs.lambda_api_name}-start-glue-jobs"
  role = aws_iam_role.lambda_function.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["glue:StartJobRun", "glue:GetJobRun"]
      Resource = "*"
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
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = var.tmdb_secret_arn
    }]
  })
}

# =========================
# READ CODE (AMBOS)
# =========================
resource "aws_iam_policy" "glue_shared_read_code" {
  name = "glue-shared-read-code"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_aux}"]
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject"]
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
        Action = ["s3:GetObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sor}/*"]
      },
      {
        Effect = "Allow"
        Action = ["s3:PutObject", "s3: DeleteObject"]
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
resource "aws_iam_role_policy" "glue_etl_start_dq" {
  name = "glue-etl-start-dq"
  role = aws_iam_role.glue_etl_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["glue:StartJobRun"]
      Resource = "*"
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
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject"]
      Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}/*"]
    }]
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
      Action = ["s3:PutObject"]
      Resource = ["arn:aws:s3:::${local.envs.s3_bucket_data_quality}/*"]
    }]
  })
}

