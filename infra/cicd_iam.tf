# =============================================================================
# cicd_iam.tf — Políticas IAM de privilégio mínimo para a role do GitHub Actions
# =============================================================================
#
# A role lsg-github-actions-{env} já existe (criada manualmente). Este arquivo
# apenas cria as políticas managed e as anexa à role existente.
# =============================================================================

data "aws_iam_role" "github_actions" {
  name = "${var.cicd_role_name}-${var.env}"
}

# =============================================================================
# POLICY 1 — BACKEND (Terraform State Lock + STS)
# =============================================================================

resource "aws_iam_policy" "cicd_backend" {
  name        = "cicd-terraform-backend-${var.env}"
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
  role       = data.aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_backend.arn
}

# =============================================================================
# POLICY 2 — S3 (Buckets do projeto + State do Terraform)
# =============================================================================

resource "aws_iam_policy" "cicd_s3" {
  name        = "cicd-terraform-s3-${var.env}"
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
  role       = data.aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_s3.arn
}

# =============================================================================
# POLICY 3 — IAM (Roles, Policies, Users do projeto + self-management)
# =============================================================================
# Segurança:
# - CRUD completo apenas em roles tmdb-* (infraestrutura do projeto)
# - Leitura-only na role CI/CD (para o data source, sem poder deletar a si mesma)
# - AttachRolePolicy com Condition restringindo quais policies podem ser anexadas
# - PassRole restrito aos 4 serviços que recebem roles do projeto

resource "aws_iam_policy" "cicd_iam" {
  name        = "cicd-terraform-iam-${var.env}"
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
        Sid    = "IAMCICDRoleReadOnly"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListRoleTags",
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.cicd_role_name}-*"
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
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.cicd_role_name}-*"
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
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/cicd-terraform-*",
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
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.cicd_role_name}-*",
        ]
        Condition = {
          ArnLike = {
            "iam:PolicyArn" = [
              "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${local.tmdb_prefix}-*",
              "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/cicd-terraform-*",
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

resource "aws_iam_role_policy_attachment" "cicd_iam" {
  role       = data.aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_iam.arn
}

# =============================================================================
# POLICY 4 — COMPUTE (Lambda + Glue Jobs/Catalog + Step Functions)
# =============================================================================

resource "aws_iam_policy" "cicd_compute" {
  name        = "cicd-terraform-compute-${var.env}"
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
        Sid      = "StepFunctionsList"
        Effect   = "Allow"
        Action   = "states:ListStateMachines"
        Resource = "*"
      },
    ]
  })

  tags = merge(local.default_resource_tags, local.component_tags.shared)
}

resource "aws_iam_role_policy_attachment" "cicd_compute" {
  role       = data.aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_compute.arn
}

# =============================================================================
# POLICY 5 — OBSERVABILIDADE (EventBridge + CloudWatch + SNS)
# =============================================================================

resource "aws_iam_policy" "cicd_observability" {
  name        = "cicd-terraform-observability-${var.env}"
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
          "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/${local.tmdb_prefix}-*",
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
  role       = data.aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.cicd_observability.arn
}

# =============================================================================
# POLICY 6 — LIGHTSAIL (Instância, KeyPair, Static IP)
# =============================================================================
# Resource restrito por tipo (Instance/*, KeyPair/*, StaticIp/*) e região
# (us-east-1). Apenas criação e listagens usam Resource "*" (obrigatório).

resource "aws_iam_policy" "cicd_lightsail" {
  name        = "cicd-terraform-lightsail-${var.env}"
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
  role       = data.aws_iam_role.github_actions.name
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
    aws_iam_role_policy_attachment.cicd_iam,
    aws_iam_role_policy_attachment.cicd_compute,
    aws_iam_role_policy_attachment.cicd_observability,
    aws_iam_role_policy_attachment.cicd_lightsail,
  ]
}
