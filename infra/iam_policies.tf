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

resource "aws_iam_role_policy" "glue_read_code_s3" {
  name = "${local.envs.iam_role_glue}-read-code"
  role = aws_iam_role.glue_job_role.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListCodePrefix"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_aux}"]
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.envs.glue_etl_job_name}/*", "${local.envs.glue_data_quality_job_name}/*"]
          }
        }
      },
      {
        Sid    = "ReadGlueArtifacts"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_aux}/${local.envs.glue_etl_job_name}/*",
          "arn:aws:s3:::${local.envs.s3_bucket_aux}/${local.envs.glue_data_quality_job_name}/*"
        ]
      }
    ]
  })
}
resource "aws_iam_role_policy" "glue_write_logs_custom_prefix" {
  name = "${local.envs.iam_role_glue}-write-logs-custom"
  role = aws_iam_role.glue_job_role.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteCustomGlueLogs"
        Effect = "Allow"
        Action = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = [
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_etl_job_name}/*",
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_etl_job_name}/*:log-stream:*",
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_data_quality_job_name}/*",
          "arn:aws:logs:*:*:log-group:/${local.envs.glue_data_quality_job_name}/*:log-stream:*"
        ]
      }
    ]
  })
}
resource "aws_iam_role_policy" "glue_start_data_quality_job" {
  name = "${local.envs.iam_role_glue}-start-data-quality"
  role = aws_iam_role.glue_job_role.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "StartAndReadDataQualityJobRun"
        Effect = "Allow"
        Action = ["glue:StartJobRun", "glue:GetJobRun"]
        Resource = "*"
      }
    ]
  })
}
resource "aws_iam_role_policy" "glue_read_sor_write_sot" {
  name = "${local.envs.iam_role_glue}-read-sor-write-sot"
  role = aws_iam_role.glue_job_role.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListSORBucket"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sor}"]
      },
      {
        Sid    = "ReadFromSOR"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sor}/*"]
      },
      {
        Sid    = "ListSOTBucket"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}"]
      },
      {
        Sid    = "WriteToSOT"
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}/*"]
      }
    ]
  })
}

# Permissions to create/update table metadata in Glue Catalog.
resource "aws_iam_role_policy" "glue_manage_catalog_tmdb" {
  name = "${local.envs.iam_role_glue}-manage-catalog-tmdb"
  role = aws_iam_role.glue_job_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManageCatalogTMDB"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:CreateDatabase",
          "glue:GetTable",
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:CreatePartition",
          "glue:BatchCreatePartition",
          "glue:UpdatePartition"
        ]
        Resource = "*"
      }
    ]
  })
}

