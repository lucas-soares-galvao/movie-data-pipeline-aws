# =============================================================================
# kms.tf — Chave KMS do trigger CustomEmailSender do Cognito (FilmBot)
# O Cognito criptografa o código de verificação com esta chave antes de repassá-lo à
# lambda_cognito_email_sender; a Lambda descriptografa via AWS Encryption SDK antes de
# enviar o e-mail pelo Gmail — ver app/lambda_cognito_email_sender/lambda_cognito_email_sender.md.
# =============================================================================

resource "aws_kms_key" "cognito_email_sender" {
  count                   = local.lightsail_agent_enabled ? 1 : 0
  description             = "Criptografa o codigo de verificacao do Cognito (FilmBot) para o trigger CustomEmailSender"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  # Sem a condição kms:EncryptionContext:userpool-id (usada no exemplo da doc oficial) de
  # propósito: usá-la aqui exigiria referenciar aws_cognito_user_pool.filmbot[0].id dentro
  # desta policy, e o próprio user pool referencia o ARN desta chave em lambda_config
  # (infra/lightsail_ia.tf) — as duas referências cruzadas formariam um ciclo de
  # dependência no grafo do Terraform. O grant de CreateGrant já é restrito a esta chave
  # específica e só ao principal da role de CI/CD, o que cobre o mesmo risco na prática.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootAccountAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        # O Cognito não assume uma role própria para isto — é a role de CI/CD (quem chama
        # UpdateUserPool ao anexar o lambda_config) que precisa de kms:CreateGrant nesta
        # chave; o Cognito usa esse grant internamente para criptografar o código. Ver
        # "Activating custom sender Lambda triggers" na doc oficial do Cognito.
        Sid    = "AllowCicdCreateGrantForCognito"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.github_actions.arn
        }
        Action   = "kms:CreateGrant"
        Resource = "*"
      },
      {
        Sid    = "AllowLambdaDecrypt"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.lambda_cognito_email_sender[0].arn
        }
        Action   = "kms:Decrypt"
        Resource = "*"
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.lambda_cognito_email_sender)
}

resource "aws_kms_alias" "cognito_email_sender" {
  count         = local.lightsail_agent_enabled ? 1 : 0
  name          = "alias/${local.tmdb_prefix}-cognito-email-sender-${var.env}"
  target_key_id = aws_kms_key.cognito_email_sender[0].key_id
}
