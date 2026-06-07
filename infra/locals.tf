# Raciocinio: centraliza caminhos e nomes derivados para evitar repeticao e erro de referencia.

locals {
  default_resource_tags = {
    Service     = "proj-eng-dados-filmes-aws"
    Environment = local.environment_tag_value
    FinOps      = var.finops_tag_value
  }
  component_tags = {
    shared = {
      Component = "shared"
    }
    lambda_api = {
      Component = "lambda_api"
    }
    eventbridge = {
      Component = "eventbridge"
    }
    glue_etl = {
      Component = "glue_etl"
    }
    glue_data_quality = {
      Component = "glue_data_quality"
    }
    glue_agg = {
      Component = "glue_agg"
    }
    glue_details = {
      Component = "glue_details"
    }
    glue_catalog = {
      Component = "glue_catalog"
    }
  }
  environment_tag_value = {
    dev   = "Dev"
    prod  = "Prod"
  }[lower(var.env)]
  eventbridge_schedule_state        = contains(["dev", "prod"], lower(var.env)) ? "ENABLED" : "DISABLED"
  lambda_api_src_path                 = "${path.root}/../app/${var.lambda_api_path_app}"
  lambda_api_requirements_path        = "${path.root}/../app/${var.lambda_api_path_app}/requirements.txt"
  lambda_api_build_path               = "${path.module}/.lambda_build"
  glue_etl_src_path                   = "${path.root}/../app/${var.glue_etl_path_app}"
  glue_etl_requirements_path          = "${path.root}/../app/${var.glue_etl_path_app}/requirements.txt"
  glue_etl_wheel_build_path           = "${path.module}/.glue_etl_build"
  glue_etl_wheel_filename             = "glue_etl_src-0.0.0-py3-none-any.whl"
  glue_data_quality_src_path          = "${path.root}/../app/${var.glue_data_quality_path_app}"
  glue_data_quality_requirements_path = "${path.root}/../app/${var.glue_data_quality_path_app}/requirements.txt"
  glue_agg_src_path                   = "${path.root}/../app/${var.glue_agg_path_app}"
  glue_agg_requirements_path          = "${path.root}/../app/${var.glue_agg_path_app}/requirements.txt"
  glue_agg_wheel_build_path           = "${path.module}/.glue_agg_build"
  glue_agg_wheel_filename             = "glue_agg_src-0.0.0-py3-none-any.whl"
  glue_details_src_path               = "${path.root}/../app/${var.glue_details_path_app}"
  glue_details_requirements_path      = "${path.root}/../app/${var.glue_details_path_app}/requirements.txt"
  glue_details_wheel_build_path       = "${path.module}/.glue_details_build"
  glue_details_wheel_filename         = "glue_details_src-0.0.0-py3-none-any.whl"
  glue_etl_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_etl_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])
  glue_data_quality_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_data_quality_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])
  glue_agg_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_agg_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])
  glue_details_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_details_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])

  lambda_alarm_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Lambda\nAlarme: <alarm_name>\nEstado: <state>\nMotivo: <reason>\nRegião: <region>\nHorário: <timestamp>"}
EOT

  eventbridge_alarm_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: EventBridge\nAlarme: <alarm_name>\nEstado: <state>\nMotivo: <reason>\nRegião: <region>\nHorário: <timestamp>"}
EOT

  glue_etl_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Glue ETL\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_data_quality_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Glue Data Quality\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_agg_succeeded_input_template = <<-EOT
{"message":"[Pipeline Sucesso Final]\nEtapa final: Glue AGG\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_agg_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Glue AGG\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_details_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Glue Details\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  envs = {
    glue_etl_job_name          = "${var.glue_etl_job_name}-${var.env}"
    glue_data_quality_job_name = "${var.glue_data_quality_job_name}-${var.env}"
    glue_agg_job_name          = "${var.glue_agg_job_name}-${var.env}"
    glue_details_job_name      = "${var.glue_details_job_name}-${var.env}"
    lambda_api_name            = "${var.lambda_api_name}-${var.env}"
    iam_role_glue              = "${var.iam_role_glue}-${var.env}"
    iam_role_lambda            = "${var.iam_role_lambda}-${var.env}"
    s3_bucket_aux              = "${var.s3_bucket_aux}-${var.env}"
    s3_bucket_temp             = "${var.s3_bucket_temp}-${var.env}"
    s3_bucket_sor              = "${var.s3_bucket_sor}-${var.env}"
    s3_bucket_sot              = "${var.s3_bucket_sot}-${var.env}"
    s3_bucket_spec             = "${var.s3_bucket_spec}-${var.env}"
    s3_bucket_data_quality     = "${var.s3_bucket_data_quality}-${var.env}"
  }
}


