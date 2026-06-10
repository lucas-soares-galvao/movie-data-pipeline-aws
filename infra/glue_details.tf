# Raciocinio: define o job Glue Details que busca runtime/temporadas via API TMDB
# e grava tb_details_movie_tmdb e tb_details_tv_tmdb no bucket SOT.
# Usa PythonShell (mesmo tipo do glue_etl e glue_agg) com timeout de 120 min —
# suficiente para ~4 000 chamadas individuais à API, sem o limite de 15 min da Lambda.

resource "aws_glue_job" "details_job_pythonshell" {
  name         = local.envs.glue_details_job_name
  description  = "Glue Details Job — coleta runtime/temporadas da API TMDB e grava no SOT"
  role_arn     = aws_iam_role.glue_details_role.arn
  max_retries  = 0
  timeout      = 120
  max_capacity = 0.0625

  command {
    script_location = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_details_job_name}/app/main.py"
    name            = "pythonshell"
    python_version  = "3.9"
  }

  notification_property {
    notify_delay_after = 3
  }

  default_arguments = {
    "--job-language"              = "python"
    "--extra-py-files"            = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_details_job_name}/${local.glue_details_wheel_filename}"
    "--additional-python-modules" = local.glue_details_additional_python_modules
    "--custom-logGroup-prefix"    = "/${local.envs.glue_details_job_name}"
    "--S3_BUCKET_SOT"             = local.envs.s3_bucket_sot
    "--S3_BUCKET_TEMP"            = local.envs.s3_bucket_temp
    "--TABLE_DISCOVER_MOVIE"      = var.glue_catalog_table_discover_movie_name
    "--TABLE_DISCOVER_TV"         = var.glue_catalog_table_discover_tv_name
    "--TABLE_DETAILS_MOVIE"           = var.glue_catalog_table_details_movie_name
    "--TABLE_DETAILS_TV"              = var.glue_catalog_table_details_tv_name
    "--TABLE_WATCH_PROVIDERS_MOVIE"   = var.glue_catalog_table_watch_providers_movie_name
    "--TABLE_WATCH_PROVIDERS_TV"      = var.glue_catalog_table_watch_providers_tv_name
    "--TMDB_SECRET_ARN"               = var.tmdb_secret_arn
    "--GLUE_AGG_JOB_NAME"          = local.envs.glue_agg_job_name
    "--GLUE_DATA_QUALITY_JOB_NAME" = local.envs.glue_data_quality_job_name
    "--ENVIRONMENT"                = var.env
  }

  tags = local.component_tags.glue_details

  depends_on = [
    aws_s3_object.deploy_scripts_bucket_details,
    aws_s3_object.deploy_app_wheel_details,
    aws_iam_role_policy_attachment.glue_details_service_role,
    aws_iam_role_policy_attachment.glue_details_read_code,
    aws_iam_role_policy.glue_details_logs,
    aws_iam_role_policy.glue_details_s3,
    aws_iam_role_policy.glue_details_catalog,
    aws_iam_role_policy.glue_details_athena,
    aws_iam_role_policy.glue_details_secrets,
    aws_iam_role_policy.glue_details_start_agg,
    aws_iam_role_policy.glue_details_start_dq,
    aws_glue_job.agg_job_pythonshell,
    aws_cloudwatch_log_group.glue_details_error,
    aws_cloudwatch_log_group.glue_details_output,
  ]

  execution_property {
    max_concurrent_runs = 4
  }
}


# ---------------------------------------------------------------------------
# Artefatos no S3
# ---------------------------------------------------------------------------

resource "aws_s3_object" "deploy_scripts_bucket_details" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.glue_details_job_name}/app/main.py"
  source     = "${local.glue_details_src_path}/main.py"
  etag       = filemd5("${local.glue_details_src_path}/main.py")
  tags       = local.component_tags.glue_details
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}

resource "null_resource" "glue_details_wheel_build" {
  triggers = {
    source_hash  = sha256(join("", [for f in fileset(local.glue_details_src_path, "src/**/*.py") : filesha256("${local.glue_details_src_path}/${f}")]))
    builder_hash = filesha256("${path.module}/scripts/build_glue_wheel.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_glue_wheel.py --src ${local.glue_details_src_path} --dest ${local.glue_details_wheel_build_path} --name glue_details_src"
  }
}

resource "aws_s3_object" "deploy_app_wheel_details" {
  bucket      = aws_s3_bucket.auxiliary_bucket.id
  key         = "${local.envs.glue_details_job_name}/${local.glue_details_wheel_filename}"
  source      = "${local.glue_details_wheel_build_path}/${local.glue_details_wheel_filename}"
  source_hash = null_resource.glue_details_wheel_build.triggers.source_hash
  tags        = local.component_tags.glue_details
  depends_on  = [null_resource.glue_details_wheel_build, aws_s3_bucket.auxiliary_bucket]
}


# ---------------------------------------------------------------------------
# IAM Role
# ---------------------------------------------------------------------------

resource "aws_iam_role" "glue_details_role" {
  name = "${local.envs.iam_role_glue}-details"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_details_service_role" {
  role       = aws_iam_role.glue_details_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy_attachment" "glue_details_read_code" {
  role       = aws_iam_role.glue_details_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}


# ---------------------------------------------------------------------------
# IAM Policies
# ---------------------------------------------------------------------------

resource "aws_iam_role_policy" "glue_details_logs" {
  name = "glue-details-logs"
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
  name = "glue-details-s3"
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
        Sid    = "ReadSOTForAthena"
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_sot}/*"]
      },
      {
        Sid    = "AthenaTemp"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::${local.envs.s3_bucket_temp}/athena/glue_details/*"]
      },
      {
        Sid    = "WriteDetailsSOT"
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_details_movie_name}/*",
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_details_tv_name}/*",
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_watch_providers_movie_name}/*",
          "arn:aws:s3:::${local.envs.s3_bucket_sot}/tmdb/${var.glue_catalog_table_watch_providers_tv_name}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "glue_details_catalog" {
  name = "glue-details-catalog"
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
  name = "glue-details-athena"
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
  name = "glue-details-secrets"
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
  name = "glue-details-start-agg"
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
  name = "glue-details-start-dq"
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


# ---------------------------------------------------------------------------
# CloudWatch Log Groups
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "glue_details_error" {
  name              = "/${local.envs.glue_details_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_details
}

resource "aws_cloudwatch_log_group" "glue_details_output" {
  name              = "/${local.envs.glue_details_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_details
}
