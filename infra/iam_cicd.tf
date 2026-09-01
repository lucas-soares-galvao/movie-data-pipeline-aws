# =============================================================================
# iam_cicd.tf — Role e políticas IAM de privilégio mínimo para o GitHub Actions
# =============================================================================
#
# A role lsg-github-actions-{env} foi originalmente criada manualmente e agora
# é importada e gerenciada pelo Terraform (max_session_duration = 3600, 1h —
# o workflow 06_backfill.yml usa exatamente essa duração e trata
# ExpiredTokenException com retomada automática via checkpoint — ver
# infra/docs/iam.md). Este arquivo também cria as políticas managed e as
# anexa à role.
# =============================================================================

resource "aws_iam_role" "github_actions" {
  name = "${local.project_config.cicd_role_name}-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:lucas-soares-galvao/*",
            ]
          }
        }
      },
    ]
  })

  max_session_duration = 3600

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

# =============================================================================
# POLICY 1 — BACKEND (Terraform State Lock + STS)
# =============================================================================

resource "aws_iam_policy" "cicd_backend" {
  name        = "${local.project_config.cicd_policy_prefix}-backend-${var.env}"
  description = "Terraform state lock (DynamoDB) e caller identity (STS)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TerraformStateLock"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeTable",
        ]
        Resource = "arn:aws:dynamodb:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.cicd_lock_dynamodb_table}"
      },
      {
        Sid      = "CallerIdentity"
        Effect   = "Allow"
        Action   = "sts:GetCallerIdentity"
        Resource = "*"
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_backend" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_backend.arn
}

# =============================================================================
# POLICY 2 — S3 (Buckets do projeto + State do Terraform)
# =============================================================================

resource "aws_iam_policy" "cicd_s3" {
  name        = "${local.project_config.cicd_policy_prefix}-s3-${var.env}"
  description = "Gerenciamento dos 6 buckets do projeto e do state file do Terraform"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3BucketDiscovery"
        Effect = "Allow"
        Action = [
          "s3:ListAllMyBuckets",
          "s3:GetBucketLocation",
        ]
        Resource = "*"
      },
      {
        Sid    = "S3ProjectBucketManagement"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:DeleteBucket",
          "s3:ListBucket",
          "s3:GetBucketPolicy",
          "s3:PutBucketPolicy",
          "s3:DeleteBucketPolicy",
          "s3:GetBucketVersioning",
          "s3:PutBucketVersioning",
          "s3:GetBucketTagging",
          "s3:PutBucketTagging",
          "s3:GetBucketPublicAccessBlock",
          "s3:PutBucketPublicAccessBlock",
          "s3:GetEncryptionConfiguration",
          "s3:PutEncryptionConfiguration",
          "s3:GetLifecycleConfiguration",
          "s3:PutLifecycleConfiguration",
          "s3:GetAccelerateConfiguration",
          "s3:GetBucketAcl",
          "s3:GetBucketCORS",
          "s3:GetBucketLogging",
          "s3:GetBucketObjectLockConfiguration",
          "s3:GetBucketRequestPayment",
          "s3:GetBucketWebsite",
          "s3:GetReplicationConfiguration",
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_aux}-*",
          "arn:aws:s3:::${var.s3_bucket_temp}-*",
          "arn:aws:s3:::${var.s3_bucket_sor}-*",
          "arn:aws:s3:::${var.s3_bucket_sot}-*",
          "arn:aws:s3:::${var.s3_bucket_spec}-*",
          "arn:aws:s3:::${var.s3_bucket_data_quality}-*",
        ]
      },
      {
        Sid    = "S3ProjectObjectManagement"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectTagging",
          "s3:PutObject",
          "s3:PutObjectTagging",
          "s3:DeleteObject",
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_aux}-*/*",
          "arn:aws:s3:::${var.s3_bucket_temp}-*/*",
          "arn:aws:s3:::${var.s3_bucket_sor}-*/*",
          "arn:aws:s3:::${var.s3_bucket_sot}-*/*",
          "arn:aws:s3:::${var.s3_bucket_spec}-*/*",
          "arn:aws:s3:::${var.s3_bucket_data_quality}-*/*",
        ]
      },
      {
        Sid    = "S3TerraformState"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketVersioning",
          "s3:GetBucketLocation",
        ]
        Resource = [
          "arn:aws:s3:::${var.cicd_statefile_s3_bucket}",
          "arn:aws:s3:::${var.cicd_statefile_s3_bucket}/*",
        ]
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_s3" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_s3.arn
}

# =============================================================================
# POLICY 3 — IAM (Roles, Policies, Users do projeto + self-management)
# =============================================================================
# Segurança:
# - CRUD completo apenas em roles tmdb-* (infraestrutura do projeto)
# - Auto-gerenciamento (Update/Tag) na própria role CI/CD, sem poder criar/deletar a si mesma
# - AttachRolePolicy com Condition restringindo quais policies podem ser anexadas
# - PassRole restrito aos 4 serviços que recebem roles do projeto

resource "aws_iam_policy" "iam_cicd" {
  name        = "${local.project_config.cicd_policy_prefix}-iam-${var.env}"
  description = "Gerenciamento de roles/policies/users tmdb-* e auto-gerenciamento da role CI/CD"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IAMProjectRoleCRUD"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:UpdateRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRoleTags",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.tmdb_prefix}-*"
      },
      {
        # Sem Create/DeleteRole — a role CI/CD não pode se auto-criar nem se
        # auto-deletar, mas precisa gerenciar seus próprios atributos (ex.:
        # max_session_duration, assume_role_policy) agora que é um resource
        # Terraform em vez de um data source.
        Sid    = "IAMCICDRoleManagement"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:UpdateRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRoleTags",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_config.cicd_role_name}-*"
      },
      {
        Sid    = "IAMInlineRolePolicyCRUD"
        Effect = "Allow"
        Action = [
          "iam:PutRolePolicy",
          "iam:GetRolePolicy",
          "iam:DeleteRolePolicy",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.tmdb_prefix}-*"
      },
      {
        Sid      = "IAMCICDInlineRolePolicyReadOnly"
        Effect   = "Allow"
        Action   = "iam:GetRolePolicy"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_config.cicd_role_name}-*"
      },
      {
        Sid    = "IAMManagedPolicyCRUD"
        Effect = "Allow"
        Action = [
          "iam:CreatePolicy",
          "iam:DeletePolicy",
          "iam:GetPolicy",
          "iam:GetPolicyVersion",
          "iam:ListPolicyVersions",
          "iam:CreatePolicyVersion",
          "iam:DeletePolicyVersion",
          "iam:TagPolicy",
          "iam:UntagPolicy",
          "iam:ListPolicyTags",
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${local.tmdb_prefix}-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${local.project_config.cicd_policy_prefix}-*",
        ]
      },
      {
        Sid    = "IAMAttachDetachPolicy"
        Effect = "Allow"
        Action = [
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.tmdb_prefix}-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_config.cicd_role_name}-*",
        ]
        Condition = {
          ArnLike = {
            "iam:PolicyArn" = [
              "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${local.tmdb_prefix}-*",
              "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${local.project_config.cicd_policy_prefix}-*",
              "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole",
            ]
          }
        }
      },
      {
        Sid    = "IAMUserManagement"
        Effect = "Allow"
        Action = [
          "iam:CreateUser",
          "iam:DeleteUser",
          "iam:GetUser",
          "iam:TagUser",
          "iam:UntagUser",
          "iam:ListUserTags",
          "iam:ListGroupsForUser",
          "iam:ListUserPolicies",
          "iam:ListAttachedUserPolicies",
          "iam:AttachUserPolicy",
          "iam:DetachUserPolicy",
          "iam:PutUserPolicy",
          "iam:GetUserPolicy",
          "iam:DeleteUserPolicy",
          "iam:CreateAccessKey",
          "iam:DeleteAccessKey",
          "iam:ListAccessKeys",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:user/${local.tmdb_prefix}-filmbot-agent-*"
      },
      {
        Sid      = "IAMPassRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.tmdb_prefix}-*"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "lambda.amazonaws.com",
              "glue.amazonaws.com",
              "events.amazonaws.com",
            ]
          }
        }
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "iam_cicd" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.iam_cicd.arn
}

# =============================================================================
# POLICY 4 — COMPUTE (Lambda + Glue Jobs/Catalog)
# =============================================================================

resource "aws_iam_policy" "cicd_compute" {
  name        = "${local.project_config.cicd_policy_prefix}-compute-${var.env}"
  description = "Gerenciamento de Lambda e Glue (jobs + catalog)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaManagement"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:ListVersionsByFunction",
          "lambda:GetPolicy",
          "lambda:AddPermission",
          "lambda:RemovePermission",
          "lambda:TagResource",
          "lambda:UntagResource",
          "lambda:ListTags",
        ]
        Resource = "arn:aws:lambda:sa-east-1:${data.aws_caller_identity.current.account_id}:function:${local.tmdb_prefix}-*"
      },
      {
        Sid    = "GlueJobManagement"
        Effect = "Allow"
        Action = [
          "glue:CreateJob",
          "glue:DeleteJob",
          "glue:GetJob",
          "glue:GetJobs",
          "glue:UpdateJob",
          "glue:BatchGetJobs",
          "glue:TagResource",
          "glue:UntagResource",
          "glue:GetTags",
        ]
        Resource = "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:job/${local.tmdb_prefix}-*"
      },
      {
        Sid    = "GlueTriggerManagement"
        Effect = "Allow"
        Action = [
          "glue:CreateTrigger",
          "glue:DeleteTrigger",
          "glue:GetTrigger",
          "glue:GetTriggers",
          "glue:UpdateTrigger",
          "glue:StartTrigger",
          "glue:StopTrigger",
          "glue:TagResource",
          "glue:UntagResource",
          "glue:GetTags",
        ]
        Resource = "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:trigger/${local.tmdb_prefix}-*"
      },
      {
        Sid    = "GlueCatalogManagement"
        Effect = "Allow"
        Action = [
          "glue:CreateDatabase",
          "glue:DeleteDatabase",
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:UpdateDatabase",
          "glue:CreateTable",
          "glue:DeleteTable",
          "glue:GetTable",
          "glue:GetTables",
          "glue:UpdateTable",
          "glue:GetPartitions",
          "glue:BatchDeletePartition",
          "glue:TagResource",
          "glue:UntagResource",
          "glue:GetTags",
        ]
        Resource = [
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/db_${local.tmdb_prefix}_*",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/db_${local.tmdb_prefix}_*/*",
        ]
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_compute" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_compute.arn
}

# =============================================================================
# POLICY 5 — OBSERVABILIDADE (EventBridge + CloudWatch + SNS)
# =============================================================================

resource "aws_iam_policy" "cicd_observability" {
  name        = "${local.project_config.cicd_policy_prefix}-observability-${var.env}"
  description = "Gerenciamento de EventBridge rules, CloudWatch logs/alarms e SNS topics"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EventBridgeRules"
        Effect = "Allow"
        Action = [
          "events:PutRule",
          "events:DeleteRule",
          "events:DescribeRule",
          "events:EnableRule",
          "events:DisableRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:ListTargetsByRule",
          "events:ListTagsForResource",
          "events:TagResource",
          "events:UntagResource",
        ]
        Resource = "arn:aws:events:sa-east-1:${data.aws_caller_identity.current.account_id}:rule/${local.tmdb_prefix}-*"
      },
      {
        Sid    = "EventBridgeApiDestination"
        Effect = "Allow"
        Action = [
          "events:CreateConnection",
          "events:DeleteConnection",
          "events:DescribeConnection",
          "events:UpdateConnection",
          "events:CreateApiDestination",
          "events:DeleteApiDestination",
          "events:DescribeApiDestination",
          "events:UpdateApiDestination",
        ]
        Resource = [
          "arn:aws:events:sa-east-1:${data.aws_caller_identity.current.account_id}:connection/${local.tmdb_prefix}-*",
          "arn:aws:events:sa-east-1:${data.aws_caller_identity.current.account_id}:api-destination/${local.tmdb_prefix}-*",
        ]
      },
      {
        # A primeira aws_cloudwatch_event_connection de API Destination criada na conta
        # exige que o EventBridge crie automaticamente esta service-linked role — sem
        # esta permissão, o CreateConnection falha com "Failed to create service linked
        # role because the caller does not have sufficient permissions". Uma vez criada,
        # é reaproveitada por qualquer connection futura da conta (fica concedida
        # permanentemente, sem custo/risco adicional). ARN/condition conforme
        # AmazonEventBridgeFullAccess (AWS managed policy).
        Sid      = "IAMCreateServiceLinkedRoleForApiDestinations"
        Effect   = "Allow"
        Action   = "iam:CreateServiceLinkedRole"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-service-role/apidestinations.events.amazonaws.com/AWSServiceRoleForAmazonEventBridgeApiDestinations"
        Condition = {
          StringEquals = {
            "iam:AWSServiceName" = "apidestinations.events.amazonaws.com"
          }
        }
      },
      {
        # Confirmado por erro real de apply: quem chama events:CreateConnection também
        # precisa de permissão direta sobre o secret que a connection cria/gerencia no
        # Secrets Manager (prefixo "events!connection/..." — não é só a service-linked
        # role que usa essas permissões, como o texto da doc da AWS sugere). Actions
        # conforme AmazonEventBridgeFullAccess (AWS managed policy), escopo restrito ao
        # padrão de nome de secret das connections deste projeto.
        Sid    = "SecretsManagerApiDestinationConnection"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:UpdateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
        ]
        Resource = "arn:aws:secretsmanager:sa-east-1:${data.aws_caller_identity.current.account_id}:secret:events!connection/${local.tmdb_prefix}-*"
      },
      {
        Sid      = "CloudWatchLogGroupsList"
        Effect   = "Allow"
        Action   = "logs:DescribeLogGroups"
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogGroups"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:PutRetentionPolicy",
          "logs:DeleteRetentionPolicy",
          "logs:ListTagsForResource",
          "logs:ListTagsLogGroup",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:TagLogGroup",
          "logs:UntagLogGroup",
        ]
        Resource = [
          "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.tmdb_prefix}-*",
          "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/aws/vendedlogs/states/${local.tmdb_prefix}-*",
          "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/${local.tmdb_prefix}-*",
          "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/lightsail/${local.tmdb_prefix}-*",
        ]
      },
      {
        Sid    = "CloudWatchAlarms"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:ListTagsForResource",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource",
        ]
        Resource = "arn:aws:cloudwatch:sa-east-1:${data.aws_caller_identity.current.account_id}:alarm:${local.tmdb_prefix}-*"
      },
      {
        Sid    = "SQSQueues"
        Effect = "Allow"
        Action = [
          "sqs:CreateQueue",
          "sqs:DeleteQueue",
          "sqs:GetQueueAttributes",
          "sqs:SetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ListQueueTags",
          "sqs:TagQueue",
          "sqs:UntagQueue",
        ]
        Resource = "arn:aws:sqs:sa-east-1:${data.aws_caller_identity.current.account_id}:${local.tmdb_prefix}-*"
      },
      {
        Sid    = "SNSTopics"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:GetTopicAttributes",
          "sns:SetTopicAttributes",
          "sns:Subscribe",
          "sns:Unsubscribe",
          "sns:GetSubscriptionAttributes",
          "sns:SetSubscriptionAttributes",
          "sns:ListSubscriptionsByTopic",
          "sns:ListTagsForResource",
          "sns:TagResource",
          "sns:UntagResource",
        ]
        Resource = "arn:aws:sns:sa-east-1:${data.aws_caller_identity.current.account_id}:${local.tmdb_prefix}-*"
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_observability" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_observability.arn
}

# =============================================================================
# POLICY 6 — LIGHTSAIL (Instância, KeyPair, Static IP) — só prod
# =============================================================================
# FilmBot (Lightsail) só existe em prod (ver local.lightsail_prod_enabled em
# infra/locals.tf) — dev não provisiona nenhum recurso Lightsail, então esta
# policy também não existe em dev. Resource restrito por tipo (Instance/*,
# KeyPair/*, StaticIp/*) e região (us-east-1). Apenas criação e listagens
# usam Resource "*" (obrigatório).

# Estes 2 recursos existiam sem `count` até a remoção do Lightsail de dev — em
# prod já estão no state em endereço "bare". Sem os `moved` abaixo, o apply
# destruiria e recriaria a policy da role de CI/CD (risco de EntityAlreadyExists
# por falta de ordenação garantida entre os dois endereços no mesmo apply).
moved {
  from = aws_iam_policy.cicd_lightsail
  to   = aws_iam_policy.cicd_lightsail[0]
}

moved {
  from = aws_iam_role_policy_attachment.cicd_lightsail
  to   = aws_iam_role_policy_attachment.cicd_lightsail[0]
}

resource "aws_iam_policy" "cicd_lightsail" {
  count       = lower(var.env) == "prod" ? 1 : 0
  name        = "${local.project_config.cicd_policy_prefix}-lightsail-${var.env}"
  description = "Gerenciamento de instância, key pair e static IP do Lightsail em us-east-1"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LightsailCreateResources"
        Effect = "Allow"
        Action = [
          "lightsail:CreateInstances",
          "lightsail:CreateKeyPair",
          "lightsail:AllocateStaticIp",
        ]
        Resource = "*"
      },
      {
        Sid    = "LightsailInstanceOperations"
        Effect = "Allow"
        Action = [
          "lightsail:DeleteInstance",
          "lightsail:StartInstance",
          "lightsail:StopInstance",
          "lightsail:PutInstancePublicPorts",
          "lightsail:CloseInstancePublicPorts",
        ]
        Resource = "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:Instance/*"
      },
      {
        Sid      = "LightsailKeyPairOperations"
        Effect   = "Allow"
        Action   = "lightsail:DeleteKeyPair"
        Resource = "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:KeyPair/*"
      },
      {
        Sid    = "LightsailStaticIpOperations"
        Effect = "Allow"
        Action = [
          "lightsail:ReleaseStaticIp",
          "lightsail:DetachStaticIp",
        ]
        Resource = "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:StaticIp/*"
      },
      {
        # AttachStaticIp exige permissão tanto no recurso StaticIp quanto no
        # Instance (ver Service Authorization Reference do Lightsail) — as
        # outras operações de Static IP não tocam em Instance/*.
        Sid    = "LightsailAttachStaticIp"
        Effect = "Allow"
        Action = "lightsail:AttachStaticIp"
        Resource = [
          "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:StaticIp/*",
          "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:Instance/*",
        ]
      },
      {
        Sid    = "LightsailTagging"
        Effect = "Allow"
        Action = [
          "lightsail:TagResource",
          "lightsail:UntagResource",
        ]
        Resource = [
          "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:Instance/*",
          "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:KeyPair/*",
          "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:StaticIp/*",
        ]
      },
      {
        Sid    = "LightsailDiscovery"
        Effect = "Allow"
        Action = [
          "lightsail:GetInstance",
          "lightsail:GetInstances",
          "lightsail:GetInstancePortStates",
          "lightsail:GetKeyPair",
          "lightsail:GetKeyPairs",
          "lightsail:GetStaticIp",
          "lightsail:GetStaticIps",
          "lightsail:GetBundles",
          "lightsail:GetBlueprints",
          "lightsail:GetRegions",
          "lightsail:GetOperation",
          "lightsail:GetOperations",
        ]
        Resource = "*"
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_lightsail" {
  count      = lower(var.env) == "prod" ? 1 : 0
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_lightsail[0].arn
}

# =============================================================================
# POLICY 7 — SSM (Parâmetros do rotation refresh, ver ssm.tf)
# =============================================================================

resource "aws_iam_policy" "cicd_ssm" {
  name        = "${local.project_config.cicd_policy_prefix}-ssm-${var.env}"
  description = "Gerenciamento dos parâmetros SSM do rotation refresh"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMRotationPointerManagement"
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:GetParameter",
          "ssm:DeleteParameter",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
          "ssm:ListTagsForResource",
        ]
        Resource = [
          "arn:aws:ssm:sa-east-1:${data.aws_caller_identity.current.account_id}:parameter/tmdb-pipeline/rotation-year-pointer-movie",
          "arn:aws:ssm:sa-east-1:${data.aws_caller_identity.current.account_id}:parameter/tmdb-pipeline/rotation-year-pointer-tv",
        ]
      },
      {
        # DescribeParameters não suporta restrição por resource (exige Resource "*").
        # O provider Terraform usa essa action para ler metadata/tags do parâmetro.
        Sid      = "SSMDescribeParameters"
        Effect   = "Allow"
        Action   = "ssm:DescribeParameters"
        Resource = "*"
      },
      {
        # Usado pelo polling de propagação (ver null_resource.cicd_policies_propagation
        # abaixo) para checar se esta própria policy já está visível no IAM antes de
        # criar os parâmetros SSM que dependem dela.
        Sid      = "IAMSimulateSelf"
        Effect   = "Allow"
        Action   = "iam:SimulatePrincipalPolicy"
        Resource = aws_iam_role.github_actions.arn
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_ssm" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_ssm.arn
}

# =============================================================================
# POLICY 8 — COGNITO (User Pool do FilmBot, ver lightsail_ia.tf)
# =============================================================================
# CreateUserPool exige Resource "*" (o ARN do pool não existe antes da
# criação — confirmado no IAM Service Authorization Reference do Cognito
# User Pools, mesmo padrão já usado para S3CreateBucket/LightsailCreateInstances
# acima). As demais actions — incluindo CreateUserPoolClient e CreateGroup,
# que operam sobre um pool já existente identificado por UserPoolId — suportam
# Resource escopado ao ARN do user pool.

resource "aws_iam_policy" "cicd_cognito" {
  name        = "${local.project_config.cicd_policy_prefix}-cognito-${var.env}"
  description = "Gerenciamento do Cognito User Pool do FilmBot"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "CognitoUserPoolCreate"
        Effect   = "Allow"
        Action   = "cognito-idp:CreateUserPool"
        Resource = "*"
      },
      {
        Sid    = "CognitoUserPoolManagement"
        Effect = "Allow"
        Action = [
          "cognito-idp:DescribeUserPool",
          "cognito-idp:UpdateUserPool",
          "cognito-idp:DeleteUserPool",
          # O provider chama AddCustomAttributes no Update quando um novo
          # bloco `schema` é adicionado a um user pool já existente (schema
          # é imutável em Create, mas aditivo depois — ver user_pool.go).
          "cognito-idp:AddCustomAttributes",
          # O provider lê a config de MFA como parte do refresh de
          # aws_cognito_user_pool (Get) e a define ao aplicar mudanças (Set) —
          # mesmo padrão de "read + write" das demais actions de gerenciamento.
          "cognito-idp:GetUserPoolMfaConfig",
          "cognito-idp:SetUserPoolMfaConfig",
          "cognito-idp:TagResource",
          "cognito-idp:UntagResource",
          "cognito-idp:ListTagsForResource",
          "cognito-idp:CreateUserPoolClient",
          "cognito-idp:DescribeUserPoolClient",
          "cognito-idp:UpdateUserPoolClient",
          "cognito-idp:DeleteUserPoolClient",
          "cognito-idp:CreateGroup",
          "cognito-idp:GetGroup",
          "cognito-idp:UpdateGroup",
          "cognito-idp:DeleteGroup",
        ]
        Resource = "arn:aws:cognito-idp:sa-east-1:${data.aws_caller_identity.current.account_id}:userpool/*"
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_cognito" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_cognito.arn
}

# =============================================================================
# POLICY 9 — KMS (Chave do trigger CustomEmailSender do Cognito, ver kms.tf)
# =============================================================================
# CreateKey/CreateAlias/ListAliases exigem Resource "*" (confirmado no IAM Service
# Authorization Reference do KMS antes de implementar, ver especialista-doc-oficial-aws —
# a chave não existe ainda no momento de CreateKey, e alias não é um recurso com ARN
# restringível por padrão de nome como os demais serviços deste projeto, já que o KMS não
# aceita wildcard em Resource para essas 3 actions). As demais actions de gerenciamento
# aceitam Resource escopado por padrão de ARN (key/*, restrito à região e conta).

resource "aws_iam_policy" "cicd_kms" {
  name        = "${local.project_config.cicd_policy_prefix}-kms-${var.env}"
  description = "Gerenciamento da chave KMS do trigger CustomEmailSender do Cognito (FilmBot)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "KMSKeyCreate"
        Effect   = "Allow"
        Action   = ["kms:CreateKey", "kms:CreateAlias", "kms:ListAliases"]
        Resource = "*"
      },
      {
        Sid    = "KMSKeyManagement"
        Effect = "Allow"
        Action = [
          "kms:DescribeKey",
          "kms:GetKeyPolicy",
          "kms:PutKeyPolicy",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:ListResourceTags",
          "kms:EnableKeyRotation",
          "kms:GetKeyRotationStatus",
          "kms:ScheduleKeyDeletion",
          "kms:CancelKeyDeletion",
          "kms:CreateGrant",
          "kms:ListGrants",
          "kms:RevokeGrant",
          "kms:UpdateAlias",
          "kms:DeleteAlias",
        ]
        Resource = "arn:aws:kms:sa-east-1:${data.aws_caller_identity.current.account_id}:key/*"
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_kms" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_kms.arn
}

# =============================================================================
# SINCRONIZAÇÃO — Garante que as policies estejam attachadas antes de criar
# qualquer recurso de infraestrutura. Sem isso, o Terraform pode tentar criar
# S3 buckets ou Lambda functions antes das policies propagarem no IAM.
#
# 9 policies em prod, 8 em dev — cicd_lightsail só existe em prod (ver
# Policy 6 acima), já que dev não provisiona nenhum recurso Lightsail.
#
# Recursos raiz (S3 buckets, IAM roles) referenciam este recurso via depends_on,
# e a dependência se propaga naturalmente para todos os recursos derivados.
# =============================================================================

resource "terraform_data" "cicd_policies_ready" {
  depends_on = [
    aws_iam_role_policy_attachment.cicd_backend,
    aws_iam_role_policy_attachment.cicd_s3,
    aws_iam_role_policy_attachment.iam_cicd,
    aws_iam_role_policy_attachment.cicd_compute,
    aws_iam_role_policy_attachment.cicd_observability,
    aws_iam_role_policy_attachment.cicd_lightsail,
    aws_iam_role_policy_attachment.cicd_ssm,
    aws_iam_role_policy_attachment.cicd_cognito,
    aws_iam_role_policy_attachment.cicd_kms,
  ]
}

# terraform_data acima só garante ORDEM (attach antes de uso), não tempo de
# propagação — IAM é eventualmente consistente, e quando a própria role
# lsg-github-actions-{env} cria/anexa uma policy nova a si mesma no mesmo
# apply (ex.: cicd_ssm num ambiente novo), a permissão pode ainda não estar
# visível nos segundos seguintes, causando AccessDenied mesmo com a policy
# já anexada. Em vez de um sleep fixo, faz polling a cada 5s via
# iam:SimulatePrincipalPolicy até a policy aparecer como "allowed" (ou até
# 60s, quando falha com mensagem explícita em vez de um AccessDenied confuso
# lá na frente).
resource "null_resource" "cicd_policies_propagation" {
  depends_on = [terraform_data.cicd_policies_ready]

  triggers = {
    ssm_policy_arn = aws_iam_policy.cicd_ssm.arn
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -uo pipefail
      for i in $(seq 1 12); do
        # A permissão iam:SimulatePrincipalPolicy também vem da policy cicd_ssm
        # sendo testada, então ela pode propagar depois da chamada abaixo já ter
        # sido feita — nesse caso o próprio simulate-principal-policy falha com
        # AccessDenied. Capturamos stderr em vez de descartar, para diferenciar
        # esse caso (chamada falhou) de "chamada OK, mas ainda há ação negada".
        if ! OUTPUT=$(aws iam simulate-principal-policy \
          --policy-source-arn "${aws_iam_role.github_actions.arn}" \
          --action-names ssm:PutParameter \
          --resource-arns "arn:aws:ssm:sa-east-1:${data.aws_caller_identity.current.account_id}:parameter/tmdb-pipeline/rotation-year-pointer-movie" \
          --query "length(EvaluationResults[?EvalDecision!=\`allowed\`])" \
          --output text 2>&1); then
          echo "Aguardando propagação da policy cicd_ssm no IAM... tentativa $i/12 (simulate-principal-policy ainda sem permissão: $OUTPUT)"
          sleep 5
          continue
        fi

        if [ "$OUTPUT" = "0" ]; then
          echo "Policy cicd_ssm propagada (tentativa $i/12)."
          exit 0
        fi

        echo "Aguardando propagação da policy cicd_ssm no IAM... tentativa $i/12 (ainda há ações negadas)"
        sleep 5
      done

      echo "Timeout aguardando propagação da policy cicd_ssm no IAM" >&2
      exit 1
    EOT
  }
}
