# =============================================================================
# lambda_cognito_email_sender.tf — Lambda do trigger CustomEmailSender do Cognito
# Deploy: código Python → build_lambda_package.py → .zip → S3 AUX → Lambda
# =============================================================================

resource "null_resource" "lambda_cognito_email_sender_build" {
  count = local.lightsail_agent_enabled ? 1 : 0

  triggers = {
    source_hash       = sha256(join("", [for f in fileset(local.lambda_cognito_email_sender_src_path, "**/*.py") : filesha256("${local.lambda_cognito_email_sender_src_path}/${f}")]))
    requirements_hash = filesha256(local.lambda_cognito_email_sender_requirements_path)
    builder_hash      = filesha256("${path.module}/scripts/build_lambda_package.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_lambda_package.py --src ${local.lambda_cognito_email_sender_src_path} --requirements ${local.lambda_cognito_email_sender_requirements_path} --dest ${local.lambda_cognito_email_sender_build_path} --platform manylinux2014_aarch64 --python-version 3.11"
  }
}

data "archive_file" "lambda_cognito_email_sender_bundle" {
  count       = local.lightsail_agent_enabled ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/lambda_cognito_email_sender_bundle.zip"
  source_dir  = local.lambda_cognito_email_sender_build_path

  depends_on = [
    null_resource.lambda_cognito_email_sender_build
  ]
}

resource "aws_s3_object" "lambda_cognito_email_sender_deploy_package" {
  count      = local.lightsail_agent_enabled ? 1 : 0
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.tmdb_prefix}/${local.envs.lambda_cognito_email_sender_name}/lambda_bundle.zip"
  source     = data.archive_file.lambda_cognito_email_sender_bundle[0].output_path
  etag       = data.archive_file.lambda_cognito_email_sender_bundle[0].output_md5
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}

resource "aws_lambda_function" "cognito_email_sender" {
  count         = local.lightsail_agent_enabled ? 1 : 0
  function_name = local.envs.lambda_cognito_email_sender_name
  role          = aws_iam_role.lambda_cognito_email_sender[0].arn
  handler       = "main.lambda_handler"
  runtime       = "python3.11"
  architectures = ["arm64"]
  timeout       = 10
  memory_size   = 256

  environment {
    variables = {
      KMS_KEY_ARN        = aws_kms_key.cognito_email_sender[0].arn
      FILMBOT_SECRET_ARN = var.filmbot_secret_arn
      ENVIRONMENT        = var.env
    }
  }

  s3_bucket        = local.envs.s3_bucket_aux
  s3_key           = aws_s3_object.lambda_cognito_email_sender_deploy_package[0].key
  source_code_hash = data.archive_file.lambda_cognito_email_sender_bundle[0].output_base64sha256
  tags             = local.component_tags.lambda_cognito_email_sender

  depends_on = [
    aws_iam_role_policy.lambda_cognito_email_sender_logs,
    aws_iam_role_policy.lambda_cognito_email_sender_secrets_manager,
    aws_iam_role_policy.lambda_cognito_email_sender_kms_decrypt,
    null_resource.lambda_cognito_email_sender_build,
    aws_s3_object.lambda_cognito_email_sender_deploy_package,
    aws_cloudwatch_log_group.lambda_cognito_email_sender_log,
  ]
}

# Autoriza o Cognito a invocar esta Lambda pelo trigger CustomEmailSender. Sem depends_on
# explícito em aws_cognito_user_pool.filmbot (ver comentário lá) — não há ciclo aqui porque
# é só esta permission que referencia o ARN do user pool, não o contrário.
resource "aws_lambda_permission" "cognito_invoke_email_sender" {
  count         = local.lightsail_agent_enabled ? 1 : 0
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cognito_email_sender[0].function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.filmbot[0].arn
}
