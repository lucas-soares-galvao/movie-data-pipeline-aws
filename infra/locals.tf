# Raciocinio: centraliza caminhos e nomes derivados para evitar repeticao e erro de referencia.

locals {
  lambda_api_src_path                 = "${path.root}/../app/${var.lambda_api_path_app}"
  lambda_api_requirements_path        = "${path.root}/../app/${var.lambda_api_path_app}/requirements.txt"
  lambda_api_build_path               = "${path.module}/.lambda_build"
  glue_etl_src_path                   = "${path.root}/../app/${var.glue_etl_path_app}"
  glue_etl_requirements_path          = "${path.root}/../app/${var.glue_etl_path_app}/requirements.txt"
  glue_data_quality_src_path          = "${path.root}/../app/${var.glue_data_quality_path_app}"
  glue_data_quality_requirements_path = "${path.root}/../app/${var.glue_data_quality_path_app}/requirements.txt"
  glue_agg_src_path                   = "${path.root}/../app/${var.glue_agg_path_app}"
  glue_agg_requirements_path          = "${path.root}/../app/${var.glue_agg_path_app}/requirements.txt"
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

  lambda_alarm_failed_input_template = <<-EOT
{"message":"[Lambda Falha]\nAlarme: <alarm_name>\nEstado: <state>\nMotivo: <reason>\nRegião: <region>\nHorário: <timestamp>"}
EOT

  lambda_alarm_success_input_template = <<-EOT
{"message":"[Lambda Sucesso]\nAlarme: <alarm_name>\nEstado: <state>\nMotivo: <reason>\nRegião: <region>\nHorário: <timestamp>"}
EOT

  eventbridge_alarm_failed_input_template = <<-EOT
{"message":"[EventBridge Falha]\nAlarme: <alarm_name>\nEstado: <state>\nMotivo: <reason>\nRegião: <region>\nHorário: <timestamp>"}
EOT

  eventbridge_alarm_success_input_template = <<-EOT
{"message":"[EventBridge Sucesso]\nAlarme: <alarm_name>\nEstado: <state>\nMotivo: <reason>\nRegião: <region>\nHorário: <timestamp>"}
EOT

  glue_etl_succeeded_input_template = <<-EOT
{"message":"[Glue ETL Sucesso]\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_etl_failed_input_template = <<-EOT
{"message":"[Glue ETL Falha]\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_data_quality_succeeded_input_template = <<-EOT
{"message":"[Glue Data Quality Sucesso]\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_data_quality_failed_input_template = <<-EOT
{"message":"[Glue Data Quality Falha]\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_agg_succeeded_input_template = <<-EOT
{"message":"[Glue AGG Sucesso]\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_agg_failed_input_template = <<-EOT
{"message":"[Glue AGG Falha]\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  envs = {
    glue_etl_job_name          = "${var.glue_etl_job_name}-${var.env}"
    glue_data_quality_job_name = "${var.glue_data_quality_job_name}-${var.env}"
    glue_agg_job_name          = "${var.glue_agg_job_name}-${var.env}"
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


