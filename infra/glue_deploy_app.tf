# Publica o script principal executado pelo Glue no bucket auxiliar.
resource "aws_s3_object" "deploy_scripts_bucket" {
  bucket = var.s3_bucket_aux
  key    = "${var.glue_etl_aux}/app/main.py"
  source = "${local.glue_etl_src_path}/main.py"
  etag   = filemd5("${local.glue_etl_src_path}/main.py")
}

# Empacota todos os modulos Python da aplicacao em um unico zip reutilizavel.
data "archive_file" "glue_app_bundle" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle.zip"

  source {
    filename = "app/__init__.py"
    content  = file("${path.root}/../app/__init__.py")
  }

  dynamic "source" {
    for_each = fileset(local.glue_etl_src_path, "**/*.py")
    content {
      filename = "app/${var.glue_etl_aux}/${source.value}"
      content  = file("${local.glue_etl_src_path}/${source.value}")
    }
  }
}

# Envia o bundle zipado para o S3, usado em --extra-py-files no Glue Job.
resource "aws_s3_object" "deploy_app_bundle" {
  bucket = var.s3_bucket_aux
  key    = "${var.glue_etl_aux}/app_bundle.zip"
  source = data.archive_file.glue_app_bundle.output_path
  etag   = filemd5(data.archive_file.glue_app_bundle.output_path)
}
