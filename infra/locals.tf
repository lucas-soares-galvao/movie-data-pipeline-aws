# Caminho local da aplicacao Python que sera empacotada e enviada ao S3.
locals {
  lambda_api_src_path            = "${path.root}/../app/${var.lambda_api_path_app}"
  glue_etl_src_path = "${path.root}/../app/${var.glue_etl_path_app}"
  glue_data_quality_src_path = "${path.root}/../app/${var.glue_data_quality_path_app}"
}
