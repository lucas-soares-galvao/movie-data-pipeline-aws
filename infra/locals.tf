# Caminho local da aplicacao Python que sera empacotada e enviada ao S3.
locals {
  lambda_api_src_path            = "${path.root}/../app/${var.lambda_api_path_app}"
  lambda_api_requirements_path   = "${path.root}/../app/${var.lambda_api_path_app}/requirements.txt"
  lambda_api_build_path          = "${path.module}/.lambda_build"
  glue_etl_src_path              = "${path.root}/../app/${var.glue_etl_path_app}"
  glue_etl_requirements_path     = "${path.root}/../app/${var.glue_etl_path_app}/requirements.txt"
  glue_data_quality_src_path     = "${path.root}/../app/${var.glue_data_quality_path_app}"
  glue_catalog_database_name     = var.glue_catalog_database_name != "" ? var.glue_catalog_database_name : "tmdb_${var.env}"
  glue_catalog_table_movies_sot  = var.glue_catalog_table_movies_sot
  glue_etl_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_etl_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])
}
