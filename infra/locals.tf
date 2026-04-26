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
}
