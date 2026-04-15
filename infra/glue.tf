resource "aws_s3_object" "deploy_scripts_bucket" {
  bucket = var.s3_bucket_aux
  key    = "glue/${var.env}/app/main.py"
  source = "${local.glue_src_path}/main.py"
  etag   = filemd5("${local.glue_src_path}/main.py")
}

data "archive_file" "glue_app_bundle" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle.zip"

  dynamic "source" {
    for_each = fileset(local.glue_src_path, "**/*.py")
    content {
      filename = "app/${source.value}"
      content  = file("${local.glue_src_path}/${source.value}")
    }
  }
}

resource "aws_s3_object" "deploy_app_bundle" {
  bucket = var.s3_bucket_aux
  key    = "glue/${var.env}/app_bundle.zip"
  source = data.archive_file.glue_app_bundle.output_path
  etag   = filemd5(data.archive_file.glue_app_bundle.output_path)
}

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
    script_location = "s3://${var.s3_bucket_aux}/glue/${var.env}/app/main.py"
    name            = "glueetl"
    python_version  = "3"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--extra-py-files"                   = "s3://${var.s3_bucket_aux}/glue/${var.env}/app_bundle.zip"
    "--continuous-log-logGroup"          = "/aws-glue/jobs"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-continuous-log-filter"     = "true"
    "--enable-metrics"                   = ""
    "--enable-auto-scaling"              = "true"
  }

  depends_on = [
    aws_s3_object.deploy_scripts_bucket,
    aws_s3_object.deploy_app_bundle
  ]

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    "ManagedBy" = "AWS"
  }
}