# =============================================================================
# lambda_glue_orchestrator.tf — Função Lambda que espera jobs Glue e aciona um job alvo
# Deploy: código Python → build_lambda_package.py → .zip → S3 AUX → Lambda
#
# Invocada sempre de forma assíncrona (InvocationType="Event") por app/lambda_api — nunca
# síncrona, nunca por EventBridge diretamente. Ver app/lambda_glue_orchestrator/
# lambda_glue_orchestrator.md para o racional (extraída da lambda_api para eliminar uma
# invocação síncrona de longa duração que causou um incidente em produção).
# =============================================================================

resource "null_resource" "lambda_glue_orchestrator_build" {
  triggers = {
    source_hash       = sha256(join("", [for f in fileset(local.lambda_glue_orchestrator_src_path, "**/*.py") : filesha256("${local.lambda_glue_orchestrator_src_path}/${f}")]))
    shared_hash       = sha256(join("", [for f in fileset(local.shared_src_path, "shared_utils/**/*.py") : filesha256("${local.shared_src_path}/${f}")]))
    requirements_hash = filesha256(local.lambda_glue_orchestrator_requirements_path)
    builder_hash      = filesha256("${path.module}/scripts/build_lambda_package.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_lambda_package.py --src ${local.lambda_glue_orchestrator_src_path} --requirements ${local.lambda_glue_orchestrator_requirements_path} --dest ${local.lambda_glue_orchestrator_build_path} --shared ${local.shared_src_path}/shared_utils"
  }
}

data "archive_file" "lambda_glue_orchestrator_bundle" {
  type        = "zip"
  output_path = "${path.module}/lambda_glue_orchestrator_bundle.zip"
  source_dir  = local.lambda_glue_orchestrator_build_path

  depends_on = [
    null_resource.lambda_glue_orchestrator_build
  ]
}

resource "aws_s3_object" "lambda_glue_orchestrator_deploy_package" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.tmdb_prefix}/${local.envs.lambda_glue_orchestrator_name}/lambda_bundle.zip"
  source     = data.archive_file.lambda_glue_orchestrator_bundle.output_path
  etag       = data.archive_file.lambda_glue_orchestrator_bundle.output_md5
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}

resource "aws_lambda_function" "lambda_glue_orchestrator" {
  function_name = local.envs.lambda_glue_orchestrator_name
  role          = aws_iam_role.lambda_glue_orchestrator.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.11"
  architectures = ["arm64"]
  timeout       = 900 # mesmo teto da lambda_api — espera jobs Glue que juntos podem levar minutos
  memory_size   = 128 # só faz polling e uma chamada de API, sem processar dado

  s3_bucket        = local.envs.s3_bucket_aux
  s3_key           = aws_s3_object.lambda_glue_orchestrator_deploy_package.key
  source_code_hash = data.archive_file.lambda_glue_orchestrator_bundle.output_base64sha256
  tags             = local.component_tags.lambda_glue_orchestrator

  depends_on = [
    aws_iam_role_policy.lambda_glue_orchestrator_logs,
    aws_iam_role_policy.lambda_glue_orchestrator_glue,
    null_resource.lambda_glue_orchestrator_build,
    aws_s3_object.lambda_glue_orchestrator_deploy_package,
    aws_cloudwatch_log_group.lambda_glue_orchestrator_log,
  ]
}
