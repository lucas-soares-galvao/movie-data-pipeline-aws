resource "aws_glue_job" "data_quality_job" {
  name              = local.envs.glue_data_quality_job_name
  description       = "Glue Data Quality Job"
  role_arn          = aws_iam_role.glue_dq_role.arn
  glue_version      = "5.0"
  job_run_queuing_enabled = true
  max_retries       = 0
  timeout           = 30
  number_of_workers = 2
  worker_type       = "G.1X"
  execution_class   = "FLEX"

  command {
    # Script principal do job armazenado no bucket auxiliar.
    # Usa "glueetl" (Spark) em vez de "pythonshell" porque o SDK de Data Quality
    # da AWS (awsglue.transforms.EvaluateDataQuality) só está disponível no runtime Spark.
    script_location = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_data_quality_job_name}/app/main.py"
    name            = "glueetl"
    python_version  = "3"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language"              = "python"
    "--extra-py-files"            = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_data_quality_job_name}/app_bundle.zip"
    "--additional-python-modules" = local.glue_data_quality_additional_python_modules
    "--custom-logGroup-prefix"    = "/${local.envs.glue_data_quality_job_name}"
    "--S3_BUCKET_DATA_QUALITY"    = local.envs.s3_bucket_data_quality
    "--ENVIRONMENT"               = var.env
    "--SNS_TOPIC_ARN_DQ_METRICS"  = aws_sns_topic.glue_data_quality_metrics_notifications.arn
    "--DATABASE_RESULTS"          = var.glue_catalog_database_unified_name
  }

  tags = local.component_tags.glue_data_quality


  # Garante que artefatos e permissoes existam antes de criar o job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_data_quality,
    aws_s3_object.deploy_app_bundle_data_quality,
    aws_iam_role_policy_attachment.glue_dq_service_role,
    aws_iam_role_policy_attachment.glue_dq_read_code,
    aws_iam_role_policy.glue_dq_logs,
    aws_cloudwatch_log_group.glue_data_quality_error,
    aws_cloudwatch_log_group.glue_data_quality_output
  ]

  execution_property {
    max_concurrent_runs = 10
  }
}


resource "aws_s3_object" "deploy_scripts_bucket_data_quality" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.glue_data_quality_job_name}/app/main.py"
  source     = "${local.glue_data_quality_src_path}/main.py"
  etag       = filemd5("${local.glue_data_quality_src_path}/main.py")
  tags       = local.component_tags.glue_data_quality
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


data "archive_file" "glue_app_bundle_data_quality" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle_data_quality.zip"
  source_dir  = local.glue_data_quality_src_path
}


resource "aws_s3_object" "deploy_app_bundle_data_quality" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.glue_data_quality_job_name}/app_bundle.zip"
  source     = data.archive_file.glue_app_bundle_data_quality.output_path
  etag       = data.archive_file.glue_app_bundle_data_quality.output_md5
  tags       = local.component_tags.glue_data_quality
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}
