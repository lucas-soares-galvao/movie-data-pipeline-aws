resource "aws_glue_job" "agg_job_pythonshell" {
  name                    = local.envs.glue_agg_job_name
  description             = "Glue AGG Job — unifica discover movie e tv no bucket SPEC"
  role_arn                = aws_iam_role.glue_agg_role.arn
  job_run_queuing_enabled = true
  max_retries             = 0
  timeout                 = 30
  max_capacity            = local.pythonshell_min_capacity

  command {
    # Script principal do job armazenado no bucket auxiliar.
    script_location = "s3://${local.envs.s3_bucket_aux}/${local.tmdb_prefix}/${local.envs.glue_agg_job_name}/app/main.py"
    name            = "pythonshell"
    python_version  = "3.9"
  }

  notification_property {
    notify_delay_after = 3 # delay in minutes
  }

  default_arguments = {
    "--job-language" = "python"
    # Pacote (wheel) com os modulos auxiliares importados pelo script principal.
    # Jobs Python Shell so adicionam .whl/.egg ao sys.path via --extra-py-files (.zip
    # nao e suportado aqui — somente em jobs Spark), por isso usamos um wheel.
    "--extra-py-files"             = "s3://${local.envs.s3_bucket_aux}/${local.tmdb_prefix}/${local.envs.glue_agg_job_name}/${local.glue_agg_wheel_filename}"
    "--additional-python-modules"  = local.glue_agg_additional_python_modules
    "--custom-logGroup-prefix"     = "/${local.envs.glue_agg_job_name}"
    "--S3_BUCKET_SPEC"             = local.envs.s3_bucket_spec
    "--S3_PREFIX_SPEC"             = local.tmdb_prefix
    "--S3_BUCKET_TEMP"             = local.envs.s3_bucket_temp
    "--DB_MOVIE"                   = local.envs.glue_catalog_db_movie
    "--DB_TV"                      = local.envs.glue_catalog_db_tv
    "--DB_UNIFIED"                 = local.envs.glue_catalog_db_unified
    "--TABLE_NAME"                 = local.envs.glue_catalog_tb_discover_unified
    "--GLUE_DATA_QUALITY_JOB_NAME" = local.envs.glue_data_quality_job_name
    "--ENVIRONMENT"                = var.env
  }

  tags = local.component_tags.glue_agg

  # Garante que artefatos e permissoes existam antes de criar o job.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_agg,
    aws_s3_object.deploy_app_wheel_agg,
    aws_iam_role_policy_attachment.glue_agg_service_role,
    aws_iam_role_policy_attachment.glue_agg_read_code,
    aws_iam_role_policy.glue_agg_logs,
    aws_iam_role_policy.glue_agg_s3,
    aws_iam_role_policy.glue_agg_catalog,
    aws_iam_role_policy.glue_agg_athena,
    aws_cloudwatch_log_group.glue_agg_error,
    aws_cloudwatch_log_group.glue_agg_output,
  ]

  execution_property {
    max_concurrent_runs = 1
  }
}


resource "aws_s3_object" "deploy_scripts_bucket_agg" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.tmdb_prefix}/${local.envs.glue_agg_job_name}/app/main.py"
  source     = "${local.glue_agg_src_path}/main.py"
  etag       = filemd5("${local.glue_agg_src_path}/main.py")
  tags       = local.component_tags.glue_agg
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


resource "null_resource" "glue_agg_wheel_build" {
  triggers = {
    source_hash  = sha256(join("", [for f in fileset(local.glue_agg_src_path, "src/**/*.py") : filesha256("${local.glue_agg_src_path}/${f}")]))
    builder_hash = filesha256("${path.module}/scripts/build_glue_wheel.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_glue_wheel.py --src ${local.glue_agg_src_path} --dest ${local.glue_agg_wheel_build_path} --name glue_agg_src"
  }
}


resource "aws_s3_object" "deploy_app_wheel_agg" {
  bucket      = aws_s3_bucket.auxiliary_bucket.id
  key         = "${local.tmdb_prefix}/${local.envs.glue_agg_job_name}/${local.glue_agg_wheel_filename}"
  source      = "${local.glue_agg_wheel_build_path}/${local.glue_agg_wheel_filename}"
  source_hash = null_resource.glue_agg_wheel_build.triggers.source_hash
  tags        = local.component_tags.glue_agg
  depends_on  = [null_resource.glue_agg_wheel_build, aws_s3_bucket.auxiliary_bucket]
}
