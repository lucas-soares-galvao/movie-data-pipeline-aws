# Defines the Glue Job responsible for running the Data Quality pipeline.
resource "aws_glue_job" "data_quality_job" {
  name              = local.envs.glue_data_quality_job_name
  description       = "Glue Data Quality Job"
  role_arn          = aws_iam_role.glue_job_role.arn
  glue_version      = "5.0"
  max_retries       = 0
  timeout           = 30
  number_of_workers = 2
  worker_type       = "G.1X"
  execution_class   = "STANDARD"

  command {
    # Main job script in the auxiliary bucket.
    script_location = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_data_quality_job_name}/app/main.py"
    name            = "glueetl"
    python_version  = "3"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language"                     = "python"
    # Bundle with auxiliary modules imported by the main script.
    "--extra-py-files"                   = "s3://${local.envs.s3_bucket_aux}/${local.envs.glue_data_quality_job_name}/app_bundle.zip"
    # Custom prefix for the groups /<job>/error and /<job>/output.
    "--custom-logGroup-prefix"           = "/${local.envs.glue_data_quality_job_name}"
    "--enable-metrics"                   = ""
    "--enable-auto-scaling"              = "true"
    "--S3_BUCKET_DATA_QUALITY"           = local.envs.s3_bucket_data_quality
    "--ENVIRONMENT"                      = var.env
  }


  # Ensure that artifacts and permissions exist before creating the job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_data_quality,
    aws_s3_object.deploy_app_bundle_data_quality,
    aws_iam_role_policy_attachment.glue_service_role,
    aws_iam_role_policy.glue_read_code_s3,
    aws_iam_role_policy.glue_write_logs_custom_prefix,
    aws_cloudwatch_log_group.glue_data_quality_error,
    aws_cloudwatch_log_group.glue_data_quality_output
  ]

  execution_property {
    max_concurrent_runs = 3
  }
}


# Publishes the main script executed by Glue to the auxiliary bucket.
resource "aws_s3_object" "deploy_scripts_bucket_data_quality" {
  bucket = aws_s3_bucket.auxiliary_bucket.id
  key    = "${local.envs.glue_data_quality_job_name}/app/main.py"
  source = "${local.glue_data_quality_src_path}/main.py"
  etag   = filemd5("${local.glue_data_quality_src_path}/main.py")
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


# Packages all Python modules of the application into a single reusable zip.
data "archive_file" "glue_app_bundle_data_quality" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle_data_quality.zip"
  source_dir  = local.glue_data_quality_src_path
}


# Uploads the zipped bundle to S3, used in --extra-py-files in the Glue Job.
resource "aws_s3_object" "deploy_app_bundle_data_quality" {
  bucket = aws_s3_bucket.auxiliary_bucket.id
  key    = "${local.envs.glue_data_quality_job_name}/app_bundle.zip"
  source = data.archive_file.glue_app_bundle_data_quality.output_path
  etag   = data.archive_file.glue_app_bundle_data_quality.output_md5
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}
