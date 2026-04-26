# Defines the Glue Job responsible for running the ETL pipeline.
resource "aws_glue_job" "etl_job" {
  name              = var.glue_etl_job_name
  description       = "Glue ETL Job"
  role_arn          = aws_iam_role.glue_job_role.arn
  glue_version      = "5.0"
  max_retries       = 0
  timeout           = 30
  number_of_workers = 2
  worker_type       = "G.1X"
  execution_class   = "STANDARD"

  command {
    # Main job script in the auxiliary bucket.
    script_location = "s3://${var.s3_bucket_aux}/${var.glue_etl_job_name}/app/main.py"
    name            = "glueetl"
    python_version  = "3"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language"                     = "python"
    # Bundle with auxiliary modules imported by the main script.
    "--extra-py-files"                   = "s3://${var.s3_bucket_aux}/${var.glue_etl_job_name}/app_bundle.zip"
    # Glue ETL dependencies installed in Glue's own Linux runtime.
    "--additional-python-modules"        = local.glue_etl_additional_python_modules
    # Custom prefix for the groups /<job>/error and /<job>/output.
    "--custom-logGroup-prefix"           = "/${var.glue_etl_job_name}"
    "--enable-metrics"                   = ""
    "--enable-auto-scaling"              = "true"
    # S3 buckets for reading (SOR) and writing (SOT)
    "--S3_BUCKET_SOR"                    = var.s3_bucket_sor
    "--S3_BUCKET_SOT"                    = var.s3_bucket_sot
    "--GLUE_CATALOG_DATABASE_NAME"       = var.glue_catalog_database_name
    "--GLUE_DATA_QUALITY_JOB_NAME"       = var.glue_data_quality_job_name
  }

  # Ensure that artifacts and permissions exist before creating the job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_etl,
    aws_s3_object.deploy_app_bundle_etl,
    aws_iam_role_policy_attachment.glue_service_role,
    aws_iam_role_policy.glue_read_code_s3,
    aws_iam_role_policy.glue_write_logs_custom_prefix,
    aws_iam_role_policy.glue_read_sor_write_sot,
    aws_iam_role_policy.glue_manage_catalog_tmdb,
    aws_glue_catalog_database.tmdb_database,
    aws_glue_catalog_table.movies_tmdb,
    aws_glue_catalog_table.tv_tmdb,
    aws_glue_catalog_table.movies_genre_tmdb,
    aws_glue_catalog_table.tv_genre_tmdb,
    aws_glue_job.data_quality_job,
    aws_cloudwatch_log_group.glue_etl_error,
    aws_cloudwatch_log_group.glue_etl_output
  ]

  execution_property {
    max_concurrent_runs = 2
  }
}


# Publishes the main script executed by Glue to the auxiliary bucket.
resource "aws_s3_object" "deploy_scripts_bucket_etl" {
  bucket = aws_s3_bucket.auxiliary_bucket.id
  key    = "${var.glue_etl_job_name}/app/main.py"
  source = "${local.glue_etl_src_path}/main.py"
  etag   = filemd5("${local.glue_etl_src_path}/main.py")
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


# Packages all Python modules of the application into a single reusable zip.
data "archive_file" "glue_app_bundle_etl" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle_etl.zip"
  source_dir  = local.glue_etl_src_path
}


# Uploads the zipped bundle to S3, used in --extra-py-files in the Glue Job.
resource "aws_s3_object" "deploy_app_bundle_etl" {
  bucket = aws_s3_bucket.auxiliary_bucket.id
  key    = "${var.glue_etl_job_name}/app_bundle.zip"
  source = data.archive_file.glue_app_bundle_etl.output_path
  etag   = data.archive_file.glue_app_bundle_etl.output_md5
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}