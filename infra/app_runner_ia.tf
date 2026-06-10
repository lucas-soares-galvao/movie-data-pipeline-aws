# ── ECR Repository ──────────────────────────────────────────────────────────────

resource "aws_ecr_repository" "app_runner_ia" {
  name                 = local.envs.app_runner_ia_ecr_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(local.default_resource_tags, local.component_tags.app_runner_ia)
}

# ── IAM: ECR Access Role (permite App Runner puxar imagem do ECR privado) ───────

resource "aws_iam_role" "app_runner_ia_ecr_access" {
  name = "${local.envs.app_runner_ia_name}-ecr-access"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "build.apprunner.amazonaws.com" }
    }]
  })

  tags = merge(local.default_resource_tags, local.component_tags.app_runner_ia)
}

resource "aws_iam_role_policy_attachment" "app_runner_ia_ecr_access" {
  role       = aws_iam_role.app_runner_ia_ecr_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# ── IAM: Instance Role (acessa AWS em runtime: Athena, S3, Secrets Manager) ─────

resource "aws_iam_role" "app_runner_ia_instance" {
  name = "${local.envs.app_runner_ia_name}-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "tasks.apprunner.amazonaws.com" }
    }]
  })

  tags = merge(local.default_resource_tags, local.component_tags.app_runner_ia)
}

resource "aws_iam_role_policy" "app_runner_ia_s3" {
  name = "${local.envs.app_runner_ia_name}-s3"
  role = aws_iam_role.app_runner_ia_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadSpec"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_spec}",
          "arn:aws:s3:::${local.envs.s3_bucket_spec}/*",
        ]
      },
      {
        Sid    = "ReadWriteTemp"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:GetBucketLocation"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_temp}",
          "arn:aws:s3:::${local.envs.s3_bucket_temp}/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy" "app_runner_ia_athena" {
  name = "${local.envs.app_runner_ia_name}-athena"
  role = aws_iam_role.app_runner_ia_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "RunAthenaQueries"
      Effect = "Allow"
      Action = [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:GetWorkGroup",
        "athena:StopQueryExecution",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "app_runner_ia_glue_catalog" {
  name = "${local.envs.app_runner_ia_name}-glue-catalog"
  role = aws_iam_role.app_runner_ia_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ReadGlueCatalog"
      Effect = "Allow"
      Action = [
        "glue:GetDatabase",
        "glue:GetTable",
        "glue:GetPartitions",
        "glue:GetPartition",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "app_runner_ia_secrets" {
  name = "${local.envs.app_runner_ia_name}-secrets"
  role = aws_iam_role.app_runner_ia_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadOpenAISecret"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [var.openai_secret_arn]
    }]
  })
}

resource "aws_iam_role_policy" "app_runner_ia_logs" {
  name = "${local.envs.app_runner_ia_name}-logs"
  role = aws_iam_role.app_runner_ia_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "WriteAppRunnerLogs"
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = [
        "arn:aws:logs:*:*:log-group:/aws/apprunner/${local.envs.app_runner_ia_name}",
        "arn:aws:logs:*:*:log-group:/aws/apprunner/${local.envs.app_runner_ia_name}:log-stream:*",
      ]
    }]
  })
}

# ── CloudWatch Log Group ─────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "app_runner_ia" {
  name              = "/aws/apprunner/${local.envs.app_runner_ia_name}"
  retention_in_days = var.log_retention_days

  tags = merge(local.default_resource_tags, local.component_tags.app_runner_ia)
}

# ── App Runner Service ───────────────────────────────────────────────────────────
# Pré-requisito: a imagem :latest deve existir no ECR antes do primeiro apply.
# Ordem de deploy: terraform apply -target=aws_ecr_repository.app_runner_ia
# → docker build + push → terraform apply

resource "aws_apprunner_service" "ia" {
  service_name = local.envs.app_runner_ia_name

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.app_runner_ia_ecr_access.arn
    }

    image_repository {
      image_identifier      = "${aws_ecr_repository.app_runner_ia.repository_url}:latest"
      image_repository_type = "ECR"

      image_configuration {
        port = "8501"

        runtime_environment_variables = {
          S3_BUCKET_SPEC    = local.envs.s3_bucket_spec
          S3_BUCKET_TEMP    = local.envs.s3_bucket_temp
          ATHENA_DATABASE   = var.glue_catalog_database_unified_name
          ATHENA_TABLE      = var.glue_agg_spec_table_name
          OPENAI_SECRET_ARN = var.openai_secret_arn
          ENVIRONMENT       = var.env
        }
      }
    }

    auto_deployments_enabled = false
  }

  instance_configuration {
    cpu               = var.app_runner_ia_cpu
    memory            = var.app_runner_ia_memory
    instance_role_arn = aws_iam_role.app_runner_ia_instance.arn
  }

  tags = merge(local.default_resource_tags, local.component_tags.app_runner_ia)
}
