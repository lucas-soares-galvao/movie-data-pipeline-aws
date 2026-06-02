# Raciocinio: define o job Glue ETL que converte SOR em SOT e publica no catalogo.

resource "aws_glue_job" "etl_job" {
  name         = local.envs.glue_etl_job_name
  description  = "Glue ETL Job"
  role_arn     = aws_iam_role.glue_etl_role.arn
  max_retries  = 0
  timeout      = 30
  max_capacity = 0.0625

  command {
    # Script principal do job armazenado no bucket auxiliar.
    script_location = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_etl_job_name}/app/main.py"
    name            = "pythonshell"
    python_version  = "3.9"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language" = "python"
    # Pacote com os modulos auxiliares importados pelo script principal.
    "--extra-py-files" = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_etl_job_name}/app_bundle.zip"
    # Dependencias do Glue ETL instaladas no proprio runtime Linux do Glue.
    "--additional-python-modules" = local.glue_etl_additional_python_modules
    # Prefixo personalizado para os grupos /<job>/error e /<job>/output.
    "--custom-logGroup-prefix" = "/${local.envs.glue_etl_job_name}"
    # Argumentos estaticos do job. Argumentos em tempo de execucao, como MEDIA_TYPE,
    # DISCOVER_TABLE, GENRE_TABLE, CONFIGURATION_TABLE, CONFIGURATION, PARTITION_COLUMNS,
    # YEAR e TABLE_SCOPE, sao fornecidos pela Lambda ao iniciar cada execucao.
    # Buckets S3 para leitura (SOR) e escrita (SOT)
    "--S3_BUCKET_SOR"              = local.envs.s3_bucket_sor
    "--S3_BUCKET_SOT"              = local.envs.s3_bucket_sot
    "--GLUE_DATA_QUALITY_JOB_NAME" = local.envs.glue_data_quality_job_name
    "--GLUE_AGG_JOB_NAME"          = local.envs.glue_agg_job_name
    "--ENVIRONMENT"                = var.env
  }

  tags = local.component_tags.glue_etl

  # Garante que artefatos e permissoes existam antes de criar o job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_etl,
    aws_s3_object.deploy_app_bundle_etl,
    aws_iam_role_policy_attachment.glue_etl_service_role,
    aws_iam_role_policy_attachment.glue_etl_read_code,
    aws_iam_role_policy.glue_etl_logs,
    aws_iam_role_policy.glue_etl_sor_sot,
    aws_iam_role_policy.glue_etl_catalog,
    aws_glue_job.data_quality_job,
    aws_glue_job.agg_job,
    aws_cloudwatch_log_group.glue_etl_error,
    aws_cloudwatch_log_group.glue_etl_output
  ]

  execution_property {
    max_concurrent_runs = 4
  }
}


# Publica o script principal executado pelo Glue no bucket auxiliar.
resource "aws_s3_object" "deploy_scripts_bucket_etl" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.glue_etl_job_name}/app/main.py"
  source     = "${local.glue_etl_src_path}/main.py"
  etag       = filemd5("${local.glue_etl_src_path}/main.py")
  tags       = local.component_tags.glue_etl
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


# Empacota todos os modulos Python da aplicacao em um unico zip reutilizavel.
data "archive_file" "glue_app_bundle_etl" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle_etl.zip"
  source_dir  = local.glue_etl_src_path
}


# Envia o pacote zipado para o S3, usado em --extra-py-files no job Glue.
resource "aws_s3_object" "deploy_app_bundle_etl" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.glue_etl_job_name}/app_bundle.zip"
  source     = data.archive_file.glue_app_bundle_etl.output_path
  etag       = data.archive_file.glue_app_bundle_etl.output_md5
  tags       = local.component_tags.glue_etl
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}
