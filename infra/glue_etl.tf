# Define o Glue Job responsavel por executar o pipeline de ETL.
resource "aws_glue_job" "etl_job" {
  name              = var.glue_etl_job_name
  description       = "Glue ETL job"
  role_arn          = aws_iam_role.glue_job_role.arn
  glue_version      = "5.0"
  max_retries       = 0
  timeout           = 30
  number_of_workers = 2
  worker_type       = "G.1X"
  execution_class   = "STANDARD"

  command {
    # Script principal do job no bucket auxiliar.
    script_location = "s3://${var.s3_bucket_aux}/${var.glue_etl_job_name}/app/main.py"
    name            = "glueetl"
    python_version  = "3"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language"                     = "python"
    # Bundle com modulos auxiliares importados pelo script principal.
    "--extra-py-files"                   = "s3://${var.s3_bucket_aux}/${var.glue_etl_job_name}/app_bundle.zip"
    # Dependencias do Glue ETL instaladas no runtime Linux do proprio Glue.
    "--additional-python-modules"        = local.glue_etl_additional_python_modules
    # Prefixo customizado para os grupos /<job>/error e /<job>/output.
    "--custom-logGroup-prefix"           = "/${var.glue_etl_job_name}"
    "--enable-metrics"                   = ""
    "--enable-auto-scaling"              = "true"
    # Buckets S3 para leitura (SOR) e escrita (SOT)
    "--S3_BUCKET_SOR"                    = var.s3_bucket_sor
    "--S3_BUCKET_SOT"                    = var.s3_bucket_sot
    "--GLUE_CATALOG_DATABASE"            = var.glue_catalog_database_name
    "--GLUE_CATALOG_TABLES"              = var.glue_catalog_table_list_name
    "--GLUE_DATA_QUALITY_JOB_NAME"       = var.glue_data_quality_job_name
  }

  # Garanta que artefatos e permissoes existam antes da criacao do job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_etl,
    aws_s3_object.deploy_app_bundle_etl,
    aws_iam_role_policy_attachment.glue_service_role,
    aws_iam_role_policy.glue_read_code_from_s3,
    aws_iam_role_policy.glue_write_logs_custom_prefix,
    aws_iam_role_policy.glue_read_sor_write_sot,
    aws_iam_role_policy.glue_manage_catalog_sot,
    aws_glue_catalog_database.sot_database,
    aws_glue_catalog_table.movies_sot,
    aws_glue_job.data_quality_job,
    aws_cloudwatch_log_group.glue_etl_job_error_log_group,
    aws_cloudwatch_log_group.glue_etl_job_output_log_group
  ]

  execution_property {
    max_concurrent_runs = 2
  }
}

# Publica o script principal executado pelo Glue no bucket auxiliar.
resource "aws_s3_object" "deploy_scripts_bucket_etl" {
  bucket = var.s3_bucket_aux
  key    = "${var.glue_etl_job_name}/app/main.py"
  source = "${local.glue_etl_src_path}/main.py"
  etag   = filemd5("${local.glue_etl_src_path}/main.py")
}

# Empacota todos os modulos Python da aplicacao em um unico zip reutilizavel.
data "archive_file" "glue_app_bundle_etl" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle_etl.zip"
  source_dir  = local.glue_etl_src_path
}

# Envia o bundle zipado para o S3, usado em --extra-py-files no Glue Job.
resource "aws_s3_object" "deploy_app_bundle_etl" {
  bucket = var.s3_bucket_aux
  key    = "${var.glue_etl_job_name}/app_bundle.zip"
  source = data.archive_file.glue_app_bundle_etl.output_path
  etag   = data.archive_file.glue_app_bundle_etl.output_md5
}