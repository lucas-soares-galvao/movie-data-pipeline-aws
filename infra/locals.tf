# Caminho local da aplicacao Python que sera empacotada e enviada ao S3.
locals {
  glue_src_path  = "${path.root}/../app"
}