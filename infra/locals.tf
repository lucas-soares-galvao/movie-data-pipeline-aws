# Local path of the Python application to be packaged and sent to S3.
locals {
  lambda_api_src_path            = "${path.root}/../app/${var.lambda_api_path_app}"
  lambda_api_requirements_path   = "${path.root}/../app/${var.lambda_api_path_app}/requirements.txt"
  lambda_api_build_path          = "${path.module}/.lambda_build"
  glue_etl_src_path              = "${path.root}/../app/${var.glue_etl_path_app}"
  glue_etl_requirements_path     = "${path.root}/../app/${var.glue_etl_path_app}/requirements.txt"
  glue_data_quality_src_path     = "${path.root}/../app/${var.glue_data_quality_path_app}"
  glue_data_quality_requirements_path = "${path.root}/../app/${var.glue_data_quality_path_app}/requirements.txt"
  glue_etl_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_etl_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])

    envs = {
      glue_etl_job_name = "${var.glue_etl_job_name}-${var.env}"
      glue_data_quality_job_name = "${var.glue_data_quality_job_name}-${var.env}"
      lambda_api_name = "${var.lambda_api_name}-${var.env}"
      iam_role_glue = "${var.iam_role_glue}-${var.env}"
      iam_role_lambda = "${var.iam_role_lambda}-${var.env}"
      s3_bucket_aux = "${var.s3_bucket_aux}-${var.env}"
      s3_bucket_temp = "${var.s3_bucket_temp}-${var.env}"
      s3_bucket_sor = "${var.s3_bucket_sor}-${var.env}"
      s3_bucket_sot = "${var.s3_bucket_sot}-${var.env}"
      s3_bucket_spec = "${var.s3_bucket_spec}-${var.env}"
      s3_bucket_data_quality = "${var.s3_bucket_data_quality}-${var.env}"
    }
}


