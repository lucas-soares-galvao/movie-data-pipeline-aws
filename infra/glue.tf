# Define o Glue Job responsavel por executar o pipeline de ETL.
resource "aws_glue_job" "etl_job" {
  name              = var.glue_job_name
  description       = "An example Glue ETL job"
  role_arn          = aws_iam_role.glue_job_role.arn
  glue_version      = "5.0"
  max_retries       = 0
  timeout           = 2880
  number_of_workers = 2
  worker_type       = "G.1X"
  execution_class   = "STANDARD"

  command {
    # Script principal do job no bucket auxiliar.
    script_location = "s3://${var.s3_bucket_aux}/glue/app/main.py"
    name            = "glueetl"
    python_version  = "3"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language"                     = "python"
    # Bundle com modulos auxiliares importados pelo script principal.
    "--extra-py-files"                   = "s3://${var.s3_bucket_aux}/glue/app_bundle.zip"
    # Prefixo customizado para criar log groups /<job>/error e /<job>/output.
    "--custom-logGroup-prefix"           = "/${var.glue_job_name}"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-continuous-log-filter"     = "true"
    "--enable-metrics"                   = ""
    "--enable-auto-scaling"              = "true"
  }

  # Garante que artefatos e permissoes existam antes da criacao do job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket,
    aws_s3_object.deploy_app_bundle,
    aws_iam_role_policy_attachment.glue_service_role,
    aws_iam_role_policy.glue_read_code_from_s3,
    aws_cloudwatch_log_group.glue_job_error_log_group,
    aws_cloudwatch_log_group.glue_job_output_log_group
  ]

  execution_property {
    max_concurrent_runs = 1
  }
}
