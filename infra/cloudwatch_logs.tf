resource "aws_cloudwatch_log_group" "glue_etl_error" {
  name              = "/${local.envs.glue_etl_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_etl
}

resource "aws_cloudwatch_log_group" "glue_etl_output" {
  name              = "/${local.envs.glue_etl_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_etl
}

resource "aws_cloudwatch_log_group" "glue_data_quality_error" {
  name              = "/${local.envs.glue_data_quality_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_data_quality
}

resource "aws_cloudwatch_log_group" "glue_data_quality_output" {
  name              = "/${local.envs.glue_data_quality_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_data_quality
}

resource "aws_cloudwatch_log_group" "lambda_log" {
  name              = "/aws/lambda/${local.envs.lambda_api_name}"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.lambda_api
}

resource "aws_cloudwatch_log_group" "glue_agg_error" {
  name              = "/${local.envs.glue_agg_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_agg
}

resource "aws_cloudwatch_log_group" "glue_agg_output" {
  name              = "/${local.envs.glue_agg_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_agg
}

resource "aws_cloudwatch_log_group" "glue_details_error" {
  name              = "/${local.envs.glue_details_job_name}/error"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_details
}

resource "aws_cloudwatch_log_group" "glue_details_output" {
  name              = "/${local.envs.glue_details_job_name}/output"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.glue_details
}

resource "aws_cloudwatch_log_group" "sfn_backfill" {
  name              = "/aws/vendedlogs/states/${local.tmdb_prefix}-sfn-backfill-${var.env}"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.sfn_backfill
}

resource "aws_cloudwatch_log_group" "lightsail_filmbot" {
  name              = "/lightsail/${local.envs.lightsail_instance_name}"
  retention_in_days = var.log_retention_days
  tags              = local.component_tags.lightsail_ia
}
