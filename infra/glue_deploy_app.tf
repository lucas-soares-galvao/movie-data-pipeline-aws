# Publica o script principal executado pelo Glue no bucket auxiliar.
resource "aws_s3_object" "deploy_scripts_bucket" {
  for_each = local.glue_jobs

  bucket = var.s3_bucket_aux
  key    = "${each.value.app_folder}/app/${each.value.script_file}"
  source = "${path.root}/../app/${each.value.app_folder}/${each.value.script_file}"
  etag   = filemd5("${path.root}/../app/${each.value.app_folder}/${each.value.script_file}")
}

# Empacota todos os modulos Python da aplicacao em um unico zip reutilizavel.
data "archive_file" "glue_app_bundle" {
  for_each = local.glue_jobs

  type        = "zip"
  output_path = "${path.module}/glue_app_bundle_${each.key}.zip"

  dynamic "source" {
    for_each = fileset("${path.root}/../app/${each.value.app_folder}", "**/*.py")
    content {
      filename = "app/${source.value}"
      content  = file("${path.root}/../app/${each.value.app_folder}/${source.value}")
    }
  }
}

# Envia o bundle zipado para o S3, usado em --extra-py-files no Glue Job.
resource "aws_s3_object" "deploy_app_bundle" {
  for_each = local.glue_jobs

  bucket = var.s3_bucket_aux
  key    = "${each.value.app_folder}/app_bundle.zip"
  source = data.archive_file.glue_app_bundle[each.key].output_path
  etag   = filemd5(data.archive_file.glue_app_bundle[each.key].output_path)
}
