# =============================================================================
# BUILD E DEPLOY DO WHEEL COMPARTILHADO (shared_src)
# =============================================================================
# Contém funções reutilizadas por múltiplos jobs Glue e pela Lambda API:
#   - shared_utils.api_client: api_get, get_api_secret
#   - shared_utils.triggers: trigger_glue_job

resource "null_resource" "shared_wheel_build" {
  triggers = {
    source_hash  = sha256(join("", [for f in fileset(local.shared_src_path, "shared_utils/**/*.py") : filesha256("${local.shared_src_path}/${f}")]))
    builder_hash = filesha256("${path.module}/scripts/build_glue_wheel.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_glue_wheel.py --src ${local.shared_src_path} --dest ${local.shared_wheel_build_path} --name tmdb_shared --package shared_utils"
  }
}


resource "aws_s3_object" "deploy_shared_wheel" {
  bucket      = aws_s3_bucket.auxiliary_bucket.id
  key         = "${local.tmdb_prefix}/shared/${local.shared_wheel_filename}"
  source      = "${local.shared_wheel_build_path}/${local.shared_wheel_filename}"
  source_hash = null_resource.shared_wheel_build.triggers.source_hash
  depends_on  = [null_resource.shared_wheel_build, aws_s3_bucket.auxiliary_bucket]
}


data "archive_file" "shared_zip" {
  type        = "zip"
  output_path = "${path.module}/${local.shared_zip_filename}"
  source_dir  = local.shared_src_path
  excludes    = ["**/__pycache__/**", "**/*.pyc", "**/*.md"]
}

resource "aws_s3_object" "deploy_shared_zip" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.tmdb_prefix}/shared/${local.shared_zip_filename}"
  source     = data.archive_file.shared_zip.output_path
  etag       = data.archive_file.shared_zip.output_md5
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}
