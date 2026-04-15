resource "aws_s3_object" "deploy_scripts_bucket" {
    bucket = var.s3_bucket_aux
    key = "glue/${var.env}/script.py"
    source = "${local.glue_src_path}/main.py"
    etag = filemd5("${local.glue_src_path}/main.py")
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
    script_location = "s3://${var.s3_bucket_aux}/${var.env}/main.py"
    name            = "glueetl"
    python_version  = "3"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--continuous-log-logGroup"          = "/aws-glue/jobs"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-continuous-log-filter"     = "true"
    "--enable-metrics"                   = ""
    "--enable-auto-scaling"              = "true"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    "ManagedBy" = "AWS"
  }
}