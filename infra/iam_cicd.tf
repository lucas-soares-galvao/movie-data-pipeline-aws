# =============================================================================
# iam_cicd.tf — Role e políticas IAM de privilégio mínimo para o GitHub Actions
# =============================================================================
#
# A role lsg-github-actions-{env} foi originalmente criada manualmente e agora
# é importada e gerenciada pelo Terraform (max_session_duration = 3600, 1h —
# o workflow 05_backfill.yml usa exatamente essa duração e trata
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
              "states.amazonaws.com",
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
# POLICY 4 — COMPUTE (Lambda + Glue Jobs/Catalog + Step Functions)
# =============================================================================

resource "aws_iam_policy" "cicd_compute" {
  name        = "${local.project_config.cicd_policy_prefix}-compute-${var.env}"
  description = "Gerenciamento de Lambda, Glue (jobs + catalog) e Step Functions"

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
          "lambda:InvokeFunction",
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
          "glue:StartJobRun",
          "glue:GetJobRun",
          "glue:TagResource",
          "glue:UntagResource",
          "glue:GetTags",
        ]
        Resource = "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:job/${local.tmdb_prefix}-*"
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
      {
        Sid    = "StepFunctionsManagement"
        Effect = "Allow"
        Action = [
          "states:CreateStateMachine",
          "states:DeleteStateMachine",
          "states:DescribeStateMachine",
          "states:UpdateStateMachine",
          "states:ListStateMachineVersions",
          "states:TagResource",
          "states:UntagResource",
          "states:ListTagsForResource",
        ]
        Resource = "arn:aws:states:sa-east-1:${data.aws_caller_identity.current.account_id}:stateMachine:${local.tmdb_prefix}-*"
      },
      {
        Sid    = "StepFunctionsList"
        Effect = "Allow"
        Action = [
          "states:ListStateMachines",
          "states:ValidateStateMachineDefinition",
        ]
        Resource = "*"
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
# POLICY 6 — LIGHTSAIL (Instância, KeyPair, Static IP)
# =============================================================================
# Resource restrito por tipo (Instance/*, KeyPair/*, StaticIp/*) e região
# (us-east-1). Apenas criação e listagens usam Resource "*" (obrigatório).

resource "aws_iam_policy" "cicd_lightsail" {
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
          "lightsail:AttachStaticIp",
          "lightsail:DetachStaticIp",
        ]
        Resource = "arn:aws:lightsail:us-east-1:${data.aws_caller_identity.current.account_id}:StaticIp/*"
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
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_lightsail.arn
}

# =============================================================================
# SINCRONIZAÇÃO — Garante que as 6 policies estejam attachadas antes de criar
# qualquer recurso de infraestrutura. Sem isso, o Terraform pode tentar criar
# S3 buckets ou Lambda functions antes das policies propagarem no IAM.
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
  ]
}
