resource "aws_glue_job" "details_job_pythonshell" {
  name                    = local.envs.glue_details_job_name
  description             = "Glue Details Job — coleta runtime/temporadas da API TMDB e grava no SOT"
  role_arn                = aws_iam_role.glue_details_role.arn
  job_run_queuing_enabled = true
  max_retries             = 0
  timeout                 = 30
  max_capacity            = local.pythonshell_min_capacity

  command {
    script_location = "s3://${local.envs.s3_bucket_aux}/${local.tmdb_prefix}/${local.envs.glue_details_job_name}/app/main.py"
    name            = "pythonshell"
    python_version  = "3.9"
  }

  notification_property {
    notify_delay_after = 3
  }

  default_arguments = {
    "--job-language"                = "python"
    "--extra-py-files"              = "s3://${local.envs.s3_bucket_aux}/${local.tmdb_prefix}/${local.envs.glue_details_job_name}/${local.glue_details_wheel_filename},s3://${local.envs.s3_bucket_aux}/${local.tmdb_prefix}/shared/${local.shared_wheel_filename}"
    "--additional-python-modules"   = local.glue_details_additional_python_modules
    "--custom-logGroup-prefix"      = "/${local.envs.glue_details_job_name}"
    "--S3_BUCKET_SOT"               = local.envs.s3_bucket_sot
    "--S3_BUCKET_TEMP"              = local.envs.s3_bucket_temp
    "--TABLE_DISCOVER_MOVIE"        = local.envs.glue_catalog_tb_discover_movie
    "--TABLE_DISCOVER_TV"           = local.envs.glue_catalog_tb_discover_tv
    "--TABLE_DETAILS_MOVIE"         = local.envs.glue_catalog_tb_details_movie
    "--TABLE_DETAILS_TV"            = local.envs.glue_catalog_tb_details_tv
    "--TABLE_WATCH_PROVIDERS_MOVIE" = local.envs.glue_catalog_tb_watch_providers_movie
    "--TABLE_WATCH_PROVIDERS_TV"    = local.envs.glue_catalog_tb_watch_providers_tv
    "--TMDB_SECRET_ARN"             = var.tmdb_secret_arn
    "--GLUE_AGG_JOB_NAME"           = local.envs.glue_agg_job_name
    "--GLUE_DATA_QUALITY_JOB_NAME"  = local.envs.glue_data_quality_job_name
    "--ENVIRONMENT"                 = var.env
  }

  tags = local.component_tags.glue_details

  depends_on = [
    aws_s3_object.deploy_scripts_bucket_details,
    aws_s3_object.deploy_app_wheel_details,
    aws_s3_object.deploy_shared_wheel,
    aws_iam_role_policy_attachment.glue_details_base,
    aws_iam_role_policy_attachment.glue_details_read_code,
    aws_iam_role_policy.glue_details_logs,
    aws_iam_role_policy.glue_details_s3,
    aws_iam_role_policy.glue_details_catalog,
    aws_iam_role_policy.glue_details_athena,
    aws_iam_role_policy.glue_details_secrets,
    aws_iam_role_policy.glue_details_start_agg,
    aws_iam_role_policy.glue_details_start_dq,
    aws_glue_job.agg_job_pythonshell,
    aws_cloudwatch_log_group.glue_details_error,
    aws_cloudwatch_log_group.glue_details_output,
  ]

  # 4 discover ETLs (2 movie + 2 TV) + 2 de buffer para retries/invocações manuais
  execution_property {
    max_concurrent_runs = 6
  }
}



resource "aws_s3_object" "deploy_scripts_bucket_details" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.tmdb_prefix}/${local.envs.glue_details_job_name}/app/main.py"
  source     = "${local.glue_details_src_path}/main.py"
  etag       = filemd5("${local.glue_details_src_path}/main.py")
  tags       = local.component_tags.glue_details
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}

resource "null_resource" "glue_details_wheel_build" {
  triggers = {
    source_hash  = sha256(join("", [for f in fileset(local.glue_details_src_path, "src/**/*.py") : filesha256("${local.glue_details_src_path}/${f}")]))
    builder_hash = filesha256("${path.module}/scripts/build_glue_wheel.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_glue_wheel.py --src ${local.glue_details_src_path} --dest ${local.glue_details_wheel_build_path} --name glue_details_src"
  }
}

resource "aws_s3_object" "deploy_app_wheel_details" {
  bucket      = aws_s3_bucket.auxiliary_bucket.id
  key         = "${local.tmdb_prefix}/${local.envs.glue_details_job_name}/${local.glue_details_wheel_filename}"
  source      = "${local.glue_details_wheel_build_path}/${local.glue_details_wheel_filename}"
  source_hash = null_resource.glue_details_wheel_build.triggers.source_hash
  tags        = local.component_tags.glue_details
  depends_on  = [null_resource.glue_details_wheel_build, aws_s3_bucket.auxiliary_bucket]
}



