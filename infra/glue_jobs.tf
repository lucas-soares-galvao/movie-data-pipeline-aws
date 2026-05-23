# Para adicionar um novo Glue Job:
# 1. Adicione uma entrada em glue_job_names e em glue_jobs (abaixo)
# 2. Crie a IAM role correspondente em iam_roles.tf com as permissões necessárias

locals {
  # Apenas valores derivados de variáveis (sempre conhecidos no plan).
  # Essa é a expressão usada no for_each de todos os recursos Glue.
  glue_job_names = {
    etl          = local.envs.glue_etl_job_name
    data_quality = local.envs.glue_data_quality_job_name
  }

  # Configuração completa por job, incluindo role_arn (referência a recurso).
  # Consultado dentro dos corpos dos recursos, onde valores desconhecidos são permitidos.
  glue_jobs = {
    etl = {
      role_arn          = aws_iam_role.glue_etl_role.arn
      src_path          = "${path.root}/../app/${var.glue_etl_path_app}"
      requirements_path = "${path.root}/../app/${var.glue_etl_path_app}/requirements.txt"
      extra_args = {
        "--S3_BUCKET_SOR"              = local.envs.s3_bucket_sor
        "--S3_BUCKET_SOT"              = local.envs.s3_bucket_sot
        "--GLUE_DATA_QUALITY_JOB_NAME" = local.envs.glue_data_quality_job_name
        "--ENVIRONMENT"                = var.env
      }
    }
    data_quality = {
      role_arn          = aws_iam_role.glue_dq_role.arn
      src_path          = "${path.root}/../app/${var.glue_data_quality_path_app}"
      requirements_path = "${path.root}/../app/${var.glue_data_quality_path_app}/requirements.txt"
      extra_args = {
        "--S3_BUCKET_DATA_QUALITY" = local.envs.s3_bucket_data_quality
        "--ENVIRONMENT"            = var.env
      }
    }
  }
}


data "archive_file" "glue_app_bundle" {
  for_each    = local.glue_job_names
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle_${each.key}.zip"
  source_dir  = local.glue_jobs[each.key].src_path
}


resource "aws_s3_object" "deploy_scripts_bucket" {
  for_each   = local.glue_job_names
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${each.value}/app/main.py"
  source     = "${local.glue_jobs[each.key].src_path}/main.py"
  etag       = filemd5("${local.glue_jobs[each.key].src_path}/main.py")
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


resource "aws_s3_object" "deploy_app_bundle" {
  for_each   = local.glue_job_names
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${each.value}/app_bundle.zip"
  source     = data.archive_file.glue_app_bundle[each.key].output_path
  etag       = data.archive_file.glue_app_bundle[each.key].output_md5
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


resource "aws_glue_job" "jobs" {
  for_each          = local.glue_job_names
  name              = each.value
  description       = "Glue ${each.key} Job"
  role_arn          = local.glue_jobs[each.key].role_arn
  glue_version      = "5.0"
  max_retries       = 0
  timeout           = 30
  number_of_workers = 2
  worker_type       = "G.1X"
  execution_class   = "STANDARD"

  command {
    script_location = "s3://${local.envs.s3_bucket_aux}/${each.value}/app/main.py"
    name            = "glueetl"
    python_version  = "3"
  }

  notification_property {
    notify_delay_after = 3
  }

  default_arguments = merge(
    {
      "--job-language"              = "python"
      "--extra-py-files"            = "s3://${local.envs.s3_bucket_aux}/${each.value}/app_bundle.zip"
      "--additional-python-modules" = join(",", [
        for line in split("\n", file(local.glue_jobs[each.key].requirements_path)) : trimspace(line)
        if trimspace(line) != "" && !startswith(trimspace(line), "#")
      ])
      "--custom-logGroup-prefix" = "/${each.value}"
      "--enable-metrics"         = ""
    },
    local.glue_jobs[each.key].extra_args
  )

  depends_on = [
    aws_s3_object.deploy_scripts_bucket,
    aws_s3_object.deploy_app_bundle,
    aws_iam_role_policy_attachment.glue_etl_service_role,
    aws_iam_role_policy_attachment.glue_etl_read_code,
    aws_iam_role_policy_attachment.glue_dq_service_role,
    aws_iam_role_policy_attachment.glue_dq_read_code,
    aws_iam_role_policy.glue_etl_logs,
    aws_iam_role_policy.glue_etl_sor_sot,
    aws_iam_role_policy.glue_etl_catalog,
    aws_iam_role_policy.glue_dq_logs,
    aws_cloudwatch_log_group.glue_etl_error,
    aws_cloudwatch_log_group.glue_etl_output,
    aws_cloudwatch_log_group.glue_data_quality_error,
    aws_cloudwatch_log_group.glue_data_quality_output,
  ]

  execution_property {
    max_concurrent_runs = 15
  }
}
