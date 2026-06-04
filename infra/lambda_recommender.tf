# Raciocinio: provisiona a Lambda de recomendacao de filmes com Function URL,
# IAM role dedicada com menor privilegio e build automatico do pacote Python.

# =========================
# BUILD E DEPLOY DO PACOTE
# =========================

resource "null_resource" "lambda_recommender_build" {
  triggers = {
    source_hash       = sha256(join("", [for f in fileset(local.lambda_recommender_src_path, "**/*.py") : filesha256("${local.lambda_recommender_src_path}/${f}")]))
    requirements_hash = filesha256(local.lambda_recommender_requirements_path)
    builder_hash      = filesha256("${path.module}/scripts/build_lambda_package.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_lambda_package.py --src ${local.lambda_recommender_src_path} --requirements ${local.lambda_recommender_requirements_path} --dest ${local.lambda_recommender_build_path}"
  }
}

data "archive_file" "lambda_recommender_bundle" {
  type        = "zip"
  output_path = "${path.module}/lambda_recommender_bundle.zip"
  source_dir  = local.lambda_recommender_build_path

  depends_on = [null_resource.lambda_recommender_build]
}

resource "aws_s3_object" "lambda_recommender_deploy_package" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.lambda_recommender_name}/lambda_recommender_bundle.zip"
  source     = data.archive_file.lambda_recommender_bundle.output_path
  etag       = data.archive_file.lambda_recommender_bundle.output_md5
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}

# =========================
# IAM ROLE
# =========================

resource "aws_iam_role" "lambda_recommender" {
  name = "${local.envs.lambda_recommender_name}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_recommender_logs" {
  name = "${local.envs.lambda_recommender_name}-logs"
  role = aws_iam_role.lambda_recommender.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "WriteLambdaLogs"
      Effect = "Allow"
      Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = [
        "arn:aws:logs:*:*:log-group:/aws/lambda/${local.envs.lambda_recommender_name}",
        "arn:aws:logs:*:*:log-group:/aws/lambda/${local.envs.lambda_recommender_name}:log-stream:*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "lambda_recommender_athena" {
  name = "${local.envs.lambda_recommender_name}-athena"
  role = aws_iam_role.lambda_recommender.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_recommender_glue_catalog" {
  name = "${local.envs.lambda_recommender_name}-glue-catalog"
  role = aws_iam_role.lambda_recommender.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_recommender_s3" {
  name = "${local.envs.lambda_recommender_name}-s3"
  role = aws_iam_role.lambda_recommender.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadSpec"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_spec}",
          "arn:aws:s3:::${local.envs.s3_bucket_spec}/*",
        ]
      },
      {
        Sid    = "AthenaTemp"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_temp}",
          "arn:aws:s3:::${local.envs.s3_bucket_temp}/athena/lambda_recommender/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_recommender_secrets" {
  name = "${local.envs.lambda_recommender_name}-secrets"
  role = aws_iam_role.lambda_recommender.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = var.openai_secret_arn
    }]
  })
}

# =========================
# CLOUDWATCH LOG GROUP
# =========================

resource "aws_cloudwatch_log_group" "lambda_recommender_log" {
  name              = "/aws/lambda/${local.envs.lambda_recommender_name}"
  retention_in_days = var.log_retention_days
}

# =========================
# LAMBDA FUNCTION
# =========================

resource "aws_lambda_function" "lambda_recommender" {
  function_name = local.envs.lambda_recommender_name
  role          = aws_iam_role.lambda_recommender.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.11"
  architectures = ["arm64"]
  timeout       = 120
  memory_size   = 512

  environment {
    variables = {
      ATHENA_DATABASE      = var.glue_catalog_database_name
      S3_BUCKET_TEMP       = local.envs.s3_bucket_temp
      OPENAI_SECRET_ARN = var.openai_secret_arn
    }
  }

  s3_bucket        = local.envs.s3_bucket_aux
  s3_key           = aws_s3_object.lambda_recommender_deploy_package.key
  source_code_hash = data.archive_file.lambda_recommender_bundle.output_base64sha256

  depends_on = [
    aws_iam_role_policy.lambda_recommender_logs,
    aws_iam_role_policy.lambda_recommender_athena,
    aws_iam_role_policy.lambda_recommender_glue_catalog,
    aws_iam_role_policy.lambda_recommender_s3,
    aws_iam_role_policy.lambda_recommender_secrets,
    aws_cloudwatch_log_group.lambda_recommender_log,
    null_resource.lambda_recommender_build,
    aws_s3_object.lambda_recommender_deploy_package,
  ]
}

# =========================
# FUNCTION URL (sem API Gateway)
# =========================

resource "aws_lambda_function_url" "lambda_recommender_url" {
  function_name      = aws_lambda_function.lambda_recommender.function_name
  authorization_type = "NONE"

  cors {
    allow_origins = ["*"]
    allow_methods = ["POST", "OPTIONS"]
    allow_headers = ["Content-Type"]
    max_age       = 300
  }
}

output "lambda_recommender_url" {
  description = "URL pública da Lambda de recomendação"
  value       = aws_lambda_function_url.lambda_recommender_url.function_url
}
