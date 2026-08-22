# Raciocinio: provisiona a instância Lightsail para hospedar o agente IA (Streamlit)
# e o IAM User com política mínima para que o app acesse Athena, S3 e Glue.

# Estes 4 recursos existiam sem `count` (incondicionais) até a remoção do
# Lightsail de dev — em prod eles já estão no state em endereço "bare" (sem
# índice). Sem os `moved` abaixo, o próximo apply em prod faria destroy+create
# em vez de só reindexar (rotacionaria a IAM access key do agente à toa).
moved {
  from = aws_iam_user.lightsail_agent
  to   = aws_iam_user.lightsail_agent[0]
}

moved {
  from = aws_iam_policy.lightsail_agent_policy
  to   = aws_iam_policy.lightsail_agent_policy[0]
}

moved {
  from = aws_iam_user_policy_attachment.lightsail_agent
  to   = aws_iam_user_policy_attachment.lightsail_agent[0]
}

moved {
  from = aws_iam_access_key.lightsail_agent
  to   = aws_iam_access_key.lightsail_agent[0]
}

resource "aws_iam_user" "lightsail_agent" {
  count      = local.lightsail_agent_enabled ? 1 : 0
  name       = "${local.tmdb_prefix}-filmbot-agent-${var.env}"
  tags       = merge(local.default_resource_tags, { Component = "lightsail_ia" })
  depends_on = [terraform_data.cicd_policies_ready]
}

resource "aws_iam_policy" "lightsail_agent_policy" {
  count       = local.lightsail_agent_enabled ? 1 : 0
  name        = "${local.tmdb_prefix}-filmbot-agent-policy-${var.env}"
  description = "Permissões mínimas para o agente IA consultar Athena, S3 e Glue"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AthenaAccess"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:GetWorkGroup",
        ]
        Resource = "arn:aws:athena:sa-east-1:${data.aws_caller_identity.current.account_id}:workgroup/primary"
      },
      {
        Sid    = "S3ReadSpec"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_spec}",
          "arn:aws:s3:::${local.envs.s3_bucket_spec}/*",
        ]
      },
      {
        Sid    = "S3AthenaTemp"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_temp}",
          "arn:aws:s3:::${local.envs.s3_bucket_temp}/*",
        ]
      },
      {
        Sid    = "GlueReadAccess"
        Effect = "Allow"
        Action = [
          "glue:GetTable",
          "glue:GetDatabase",
          "glue:GetPartitions",
          "glue:GetPartition",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${local.envs.glue_catalog_db_unified}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${local.envs.glue_catalog_db_unified}/*",
        ]
      },
      {
        Sid    = "CloudWatchLogsAccess"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
        ]
        Resource = "${aws_cloudwatch_log_group.lightsail_filmbot[0].arn}:*"
      },
      {
        # Todas as actions abaixo suportam Resource escopado ao user pool
        # (confirmado no IAM Service Authorization Reference antes de
        # implementar, ver especialista-doc-oficial-aws).
        Sid    = "CognitoUserManagement"
        Effect = "Allow"
        Action = [
          "cognito-idp:SignUp",
          "cognito-idp:ForgotPassword",
          "cognito-idp:ConfirmForgotPassword",
          "cognito-idp:AdminInitiateAuth",
          "cognito-idp:AdminConfirmSignUp",
          "cognito-idp:AdminUpdateUserAttributes",
          "cognito-idp:AdminDisableUser",
          "cognito-idp:AdminEnableUser",
          "cognito-idp:AdminDeleteUser",
          "cognito-idp:AdminAddUserToGroup",
          "cognito-idp:AdminListGroupsForUser",
          "cognito-idp:ListUsers",
        ]
        Resource = aws_cognito_user_pool.filmbot[0].arn
      },
      {
        Sid    = "SnsPublishNewSignup"
        Effect = "Allow"
        Action = [
          "sns:Publish",
        ]
        Resource = aws_sns_topic.filmbot_new_signup_notifications.arn
      },
    ]
  })

  tags = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

resource "aws_iam_user_policy_attachment" "lightsail_agent" {
  count      = local.lightsail_agent_enabled ? 1 : 0
  user       = aws_iam_user.lightsail_agent[0].name
  policy_arn = aws_iam_policy.lightsail_agent_policy[0].arn
}

resource "aws_iam_access_key" "lightsail_agent" {
  count = local.lightsail_agent_enabled ? 1 : 0
  user  = aws_iam_user.lightsail_agent[0].name
}

# =============================================================================
# COGNITO — Identidade/usuários do FilmBot (login, cadastro, aprovação, reset)
# =============================================================================
# Mesmo gate do agente (lightsail_agent_enabled, não lightsail_prod_enabled):
# sem custo relevante nesse volume (free tier de 10k MAU/mês) e não depende da
# instância — permite testar o app localmente contra o Cognito de dev, mesmo
# racional de existir em dev e prod já aplicado ao IAM user do agente acima.
resource "aws_cognito_user_pool" "filmbot" {
  count = local.lightsail_agent_enabled ? 1 : 0
  name  = "${local.tmdb_prefix}-filmbot-users-${var.env}"

  # Sem isso, o Terraform pode tentar criar o pool antes da policy cicd_cognito
  # estar de fato anexada/propagada na role de CI/CD (mesmo racional do
  # depends_on em aws_iam_user.lightsail_agent, linha ~32 acima) — foi
  # exatamente essa race que causou AccessDeniedException em CreateUserPool
  # mesmo depois da policy já existir no código.
  depends_on = [terraform_data.cicd_policies_ready]

  # Login por e-mail, sem username separado.
  username_attributes = ["email"]

  # Vazio de propósito: o cadastro (SignUp) não dispara nenhum código
  # automático — o gate de acesso é a aprovação manual do admin
  # (AdminConfirmSignUp no painel admin), não um código de verificação.
  auto_verified_attributes = []

  admin_create_user_config {
    allow_admin_create_user_only = false # cadastro público (SignUp) — aprovado manualmente depois
  }

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  # Necessário para o ForgotPassword saber para onde mandar o código — só
  # funciona depois que o admin marcar email_verified=true na aprovação
  # (ver AdminUpdateUserAttributes em src/infrastructure.py).
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  schema {
    name                = "name"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  # Sem email_configuration de propósito: usa o remetente nativo do próprio
  # Cognito (não configurado com SES) — decisão do projeto para não depender
  # de identidade SES verificada/production access nesta primeira versão.
  tags = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

resource "aws_cognito_user_pool_client" "filmbot" {
  count        = local.lightsail_agent_enabled ? 1 : 0
  name         = "${local.tmdb_prefix}-filmbot-client-${var.env}"
  user_pool_id = aws_cognito_user_pool.filmbot[0].id

  generate_secret = false # todas as chamadas partem do backend (boto3, IAM), nunca do navegador

  explicit_auth_flows = [
    "ALLOW_ADMIN_USER_PASSWORD_AUTH", # login via AdminInitiateAuth, chamado pelo backend
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  prevent_user_existence_errors = "ENABLED" # não vaza se um e-mail já está cadastrado
}

resource "aws_cognito_user_group" "admins" {
  count        = local.lightsail_agent_enabled ? 1 : 0
  name         = "admins"
  user_pool_id = aws_cognito_user_pool.filmbot[0].id
  description  = "Usuários com acesso ao painel administrativo do FilmBot"
}

resource "aws_lightsail_key_pair" "filmbot" {
  count    = local.lightsail_prod_enabled ? 1 : 0
  provider = aws.lightsail
  name     = "${local.tmdb_prefix}-filmbot-key-${var.env}"
  tags     = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

resource "aws_lightsail_instance" "filmbot" {
  count             = local.lightsail_prod_enabled ? 1 : 0
  provider          = aws.lightsail
  name              = local.envs.lightsail_instance_name
  availability_zone = "us-east-1a"
  blueprint_id      = "ubuntu_22_04"
  bundle_id         = var.lightsail_bundle_id
  key_pair_name     = aws_lightsail_key_pair.filmbot[0].name
  tags              = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

resource "aws_lightsail_instance_public_ports" "filmbot" {
  count         = local.lightsail_prod_enabled ? 1 : 0
  provider      = aws.lightsail
  instance_name = aws_lightsail_instance.filmbot[0].name

  port_info {
    from_port = 22
    to_port   = 22
    protocol  = "tcp"
    cidrs     = var.lightsail_ssh_allowed_cidrs
  }

  port_info {
    from_port = 80
    to_port   = 80
    protocol  = "tcp"
    cidrs     = ["0.0.0.0/0"]
  }

  port_info {
    from_port = 443
    to_port   = 443
    protocol  = "tcp"
    cidrs     = ["0.0.0.0/0"]
  }
}

resource "aws_lightsail_static_ip" "filmbot" {
  count    = local.lightsail_prod_enabled ? 1 : 0
  provider = aws.lightsail
  name     = "${local.tmdb_prefix}-filmbot-static-ip-${var.env}"
}

resource "aws_lightsail_static_ip_attachment" "filmbot" {
  count          = local.lightsail_prod_enabled ? 1 : 0
  provider       = aws.lightsail
  static_ip_name = aws_lightsail_static_ip.filmbot[0].name
  instance_name  = aws_lightsail_instance.filmbot[0].name
}

# FilmBot só existe em prod, sempre com IP fixo (static IP) — ver
# local.lightsail_prod_enabled em infra/locals.tf.
output "lightsail_public_ip" {
  description = "IP público (fixo) da instância Lightsail"
  value       = length(aws_lightsail_static_ip.filmbot) > 0 ? aws_lightsail_static_ip.filmbot[0].ip_address : ""
}

output "lightsail_url" {
  description = "URL do FilmBot — clicável no terminal"
  value       = length(aws_lightsail_instance.filmbot) > 0 ? "http://${aws_lightsail_instance.filmbot[0].public_ip_address}" : ""
}

output "lightsail_private_key" {
  description = "Chave privada SSH para acessar a instância via ssh -i <key> ubuntu@<ip>"
  value       = length(aws_lightsail_key_pair.filmbot) > 0 ? aws_lightsail_key_pair.filmbot[0].private_key : ""
  sensitive   = true
}

output "lightsail_agent_access_key_id" {
  description = "AWS_ACCESS_KEY_ID para o arquivo .env na instância"
  value       = length(aws_iam_access_key.lightsail_agent) > 0 ? aws_iam_access_key.lightsail_agent[0].id : ""
  sensitive   = true
}

output "lightsail_agent_secret_access_key" {
  description = "AWS_SECRET_ACCESS_KEY para o arquivo .env na instância"
  value       = length(aws_iam_access_key.lightsail_agent) > 0 ? aws_iam_access_key.lightsail_agent[0].secret : ""
  sensitive   = true
}

output "lightsail_instance_name" {
  description = "Nome da instância Lightsail para verificação de estado"
  value       = length(aws_lightsail_instance.filmbot) > 0 ? aws_lightsail_instance.filmbot[0].name : ""
}

output "lightsail_cloudwatch_log_group" {
  description = "CLOUDWATCH_LOG_GROUP para o arquivo .env na instância"
  value       = length(aws_cloudwatch_log_group.lightsail_filmbot) > 0 ? aws_cloudwatch_log_group.lightsail_filmbot[0].name : ""
}

output "lightsail_filmbot_secret_arn" {
  description = "ARN do segredo no Secrets Manager com llm_api_key, tmdb_api_key, filmbot_password e transcription_api_key (opcional)"
  value       = var.filmbot_secret_arn
}

output "lightsail_athena_s3_output" {
  description = "ATHENA_S3_OUTPUT para o arquivo .env na instância (caminho S3 para resultados temporários do Athena)"
  value       = "s3://${local.envs.s3_bucket_temp}/${local.tmdb_prefix}/athena/lightsail_ia"
}

output "lightsail_glue_database" {
  description = "GLUE_DATABASE para o arquivo .env na instância"
  value       = local.envs.glue_catalog_db_unified
}

output "lightsail_spec_table" {
  description = "SPEC_TABLE para o arquivo .env na instância (tabela SPEC, registrada em runtime pelo Glue AGG)"
  value       = local.envs.glue_catalog_tb_discover_unified
}

output "lightsail_cognito_user_pool_id" {
  description = "COGNITO_USER_POOL_ID para o arquivo .env na instância"
  value       = length(aws_cognito_user_pool.filmbot) > 0 ? aws_cognito_user_pool.filmbot[0].id : ""
}

output "lightsail_cognito_app_client_id" {
  description = "COGNITO_APP_CLIENT_ID para o arquivo .env na instância"
  value       = length(aws_cognito_user_pool_client.filmbot) > 0 ? aws_cognito_user_pool_client.filmbot[0].id : ""
}

output "lightsail_sns_new_signup_topic_arn" {
  description = "SNS_NEW_SIGNUP_TOPIC_ARN para o arquivo .env na instância"
  value       = aws_sns_topic.filmbot_new_signup_notifications.arn
}
