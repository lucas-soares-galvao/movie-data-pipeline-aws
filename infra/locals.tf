# Caminho local da aplicacao Python que sera empacotada e enviada ao S3.
locals {
  lambda_api_src_path            = "${path.root}/../app/${var.lambda_api_path_app}"
  lambda_api_requirements_path   = "${path.root}/../app/${var.lambda_api_path_app}/requirements.txt"
  lambda_api_build_path          = "${path.module}/.lambda_build"
  glue_etl_src_path              = "${path.root}/../app/${var.glue_etl_path_app}"
  glue_etl_requirements_path     = "${path.root}/../app/${var.glue_etl_path_app}/requirements.txt"
  glue_etl_build_path            = "${path.module}/.glue_etl_build"
  glue_data_quality_src_path     = "${path.root}/../app/${var.glue_data_quality_path_app}"
  glue_data_quality_requirements_path = "${path.root}/../app/${var.glue_data_quality_path_app}/requirements.txt"
  glue_data_quality_build_path   = "${path.module}/.glue_data_quality_build"
}
