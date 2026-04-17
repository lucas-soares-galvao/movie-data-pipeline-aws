# Caminho local da aplicacao Python que sera empacotada e enviada ao S3.
locals {
  glue_etl_src_path = "${path.root}/../app/${var.glue_etl_aux}"
}
