resource "aws_s3_object" "deploy_scripts_bucket" {
  bucket = var.s3_bucket_aux
  key    = "glue/${var.env}/app/main.py"
  source = "${local.glue_src_path}/main.py"
  etag   = filemd5("${local.glue_src_path}/main.py")
}

data "archive_file" "glue_app_bundle" {
  type        = "zip"
  output_path = "${path.module}/glue_app_bundle.zip"

  dynamic "source" {
    for_each = fileset(local.glue_src_path, "**/*.py")
    content {
      filename = "app/${source.value}"
      content  = file("${local.glue_src_path}/${source.value}")
    }
  }
}

resource "aws_s3_object" "deploy_app_bundle" {
  bucket = var.s3_bucket_aux
  key    = "glue/${var.env}/app_bundle.zip"
  source = data.archive_file.glue_app_bundle.output_path
  etag   = filemd5(data.archive_file.glue_app_bundle.output_path)
}