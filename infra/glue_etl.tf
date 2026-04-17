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
    # Prefixo customizado para os grupos /<job>/error e /<job>/output.
    "--custom-logGroup-prefix"           = "/${var.glue_etl_job_name}"
    "--enable-metrics"                   = ""
    "--enable-auto-scaling"              = "true"
  }

  # Garante que artefatos e permissoes existam antes da criacao do job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_etl,
    aws_s3_object.deploy_app_bundle_etl,
    aws_iam_role_policy_attachment.glue_service_role,
    aws_iam_role_policy.glue_read_code_from_s3,
    aws_iam_role_policy.glue_write_logs_custom_prefix,
    aws_cloudwatch_log_group.glue_etl_job_error_log_group,
    aws_cloudwatch_log_group.glue_etl_job_output_log_group
  ]

  execution_property {
    max_concurrent_runs = 1
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

  source {
    filename = "app/__init__.py"
    content  = file("${path.root}/../app/__init__.py")
  }

  dynamic "source" {
    for_each = fileset(local.glue_etl_src_path, "**/*.py")
    content {
      filename = "app/${var.glue_etl_job_name}/${source.value}"
      content  = file("${local.glue_etl_src_path}/${source.value}")
    }
  }
}

# Envia o bundle zipado para o S3, usado em --extra-py-files no Glue Job.
resource "aws_s3_object" "deploy_app_bundle_etl" {
  bucket = var.s3_bucket_aux
  key    = "${var.glue_etl_job_name}/app_bundle.zip"
  source = data.archive_file.glue_app_bundle_etl.output_path
  etag   = filemd5(data.archive_file.glue_app_bundle_etl.output_path)
}