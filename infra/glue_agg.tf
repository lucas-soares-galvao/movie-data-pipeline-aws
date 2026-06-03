# Raciocinio: define o job Glue AGG que executa a query de unificacao via Athena
# e grava os dados particionados por media_type e year no bucket SPEC.
# O AWS Wrangler registra/atualiza a tabela no Glue Catalog automaticamente.

resource "aws_glue_job" "agg_job_pythonshell" {
  name         = local.envs.glue_agg_job_name
  description  = "Glue AGG Job — unifica discover movie e tv no bucket SPEC"
  role_arn     = aws_iam_role.glue_agg_role.arn
  max_retries  = 0
  timeout      = 30
  max_capacity = 0.0625

  command {
    # Script principal do job armazenado no bucket auxiliar.
    script_location = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_agg_job_name}/app/main.py"
    name            = "pythonshell"
    python_version  = "3.9"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language"              = "python"
    "--extra-py-files"            = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_agg_job_name}/app_bundle.zip"
    "--additional-python-modules" = local.glue_agg_additional_python_modules
    "--custom-logGroup-prefix"    = "/${local.envs.glue_agg_job_name}"
    "--S3_BUCKET_SPEC"            = local.envs.s3_bucket_spec
    "--S3_BUCKET_TEMP"            = local.envs.s3_bucket_temp
    "--DATABASE"                  = var.glue_catalog_database_name
    "--TABLE_NAME"                = var.glue_agg_spec_table_name
    "--ENVIRONMENT"               = var.env
  }

  tags = local.component_tags.glue_agg

  # Garante que artefatos e permissoes existam antes de criar o job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_agg,
    aws_s3_object.deploy_app_bundle_agg,
    aws_iam_role_policy_attachment.glue_agg_service_role,
    aws_iam_role_policy_attachment.glue_agg_read_code,
    aws_iam_role_policy.glue_agg_logs,
    aws_iam_role_policy.glue_agg_s3,
    aws_iam_role_policy.glue_agg_catalog,
    aws_iam_role_policy.glue_agg_athena,
    aws_cloudwatch_log_group.glue_agg_error,
    aws_cloudwatch_log_group.glue_agg_output,
  ]

  execution_property {
    max_concurrent_runs = 1
  }
}


# Publica o script principal executado pelo Glue no bucket auxiliar.
resource "aws_s3_object" "deploy_scripts_bucket_agg" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.glue_agg_job_name}/app/main.py"
  source     = "${local.glue_agg_src_path}/main.py"
  etag       = filemd5("${local.glue_agg_src_path}/main.py")
  tags       = local.component_tags.glue_agg
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


# Empacota src/ como subdiretorio no zip para que `from src.utils import ...` funcione.
data "archive_file" "glue_app_bundle_agg" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle_agg.zip"

  source {
    content  = file("${local.glue_agg_src_path}/src/__init__.py")
    filename = "src/__init__.py"
  }

  source {
    content  = file("${local.glue_agg_src_path}/src/utils.py")
    filename = "src/utils.py"
  }
}


# Envia o pacote zipado para o S3, usado em --extra-py-files no job Glue.
resource "aws_s3_object" "deploy_app_bundle_agg" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.glue_agg_job_name}/app_bundle.zip"
  source     = data.archive_file.glue_app_bundle_agg.output_path
  etag       = data.archive_file.glue_app_bundle_agg.output_md5
  tags       = local.component_tags.glue_agg
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}
