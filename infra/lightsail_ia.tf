# Raciocinio: provisiona a instância Lightsail para hospedar o agente IA (Streamlit)
# e o IAM User com política mínima para que o app acesse Athena, S3 e Glue.

# ── IAM User dedicado para o agente IA ───────────────────────────────────────

resource "aws_iam_user" "lightsail_agent" {
  name = "filmbot-agent-${var.env}"
  tags = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

resource "aws_iam_policy" "lightsail_agent_policy" {
  name        = "filmbot-agent-policy-${var.env}"
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
        Sid    = "S3Access"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          "arn:aws:s3:::${local.envs.s3_bucket_spec}",
          "arn:aws:s3:::${local.envs.s3_bucket_spec}/*",
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
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:database/${var.glue_catalog_database_unified_name}",
          "arn:aws:glue:sa-east-1:${data.aws_caller_identity.current.account_id}:table/${var.glue_catalog_database_unified_name}/*",
        ]
      },
    ]
  })

  tags = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

resource "aws_iam_user_policy_attachment" "lightsail_agent" {
  user       = aws_iam_user.lightsail_agent.name
  policy_arn = aws_iam_policy.lightsail_agent_policy.arn
}

resource "aws_iam_access_key" "lightsail_agent" {
  user = aws_iam_user.lightsail_agent.name
}

# ── Lightsail: key pair SSH ───────────────────────────────────────────────────

resource "aws_lightsail_key_pair" "filmbot" {
  count    = var.lightsail_enabled ? 1 : 0
  provider = aws.lightsail
  name     = "filmbot-key-${var.env}"
  tags     = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

# ── Lightsail: instância ──────────────────────────────────────────────────────

resource "aws_lightsail_instance" "filmbot" {
  count             = var.lightsail_enabled ? 1 : 0
  provider          = aws.lightsail
  name              = "${var.lightsail_instance_name}-${var.env}"
  availability_zone = "us-east-1a"
  blueprint_id      = "ubuntu_22_04"
  bundle_id         = "nano_3_0"  # 512 MB RAM, 2 vCPU, 20 GB SSD — $3,50/mês
  key_pair_name     = aws_lightsail_key_pair.filmbot[0].name
  tags              = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

# ── Lightsail: abertura de portas ─────────────────────────────────────────────

resource "aws_lightsail_instance_public_ports" "filmbot" {
  count         = var.lightsail_enabled ? 1 : 0
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

  port_info {
    from_port = 8501
    to_port   = 8501
    protocol  = "tcp"
    cidrs     = ["0.0.0.0/0"]
  }
}

# ── Lightsail: IP estático ────────────────────────────────────────────────────

resource "aws_lightsail_static_ip" "filmbot" {
  count    = var.lightsail_enabled ? 1 : 0
  provider = aws.lightsail
  name     = "filmbot-static-ip-${var.env}"
}

resource "aws_lightsail_static_ip_attachment" "filmbot" {
  count          = var.lightsail_enabled ? 1 : 0
  provider       = aws.lightsail
  static_ip_name = aws_lightsail_static_ip.filmbot[0].name
  instance_name  = aws_lightsail_instance.filmbot[0].name
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "lightsail_public_ip" {
  description = "IP público fixo da instância Lightsail — use este IP no A record do is-a.dev (filmbot.is-a.dev)"
  value       = var.lightsail_enabled ? aws_lightsail_static_ip.filmbot[0].ip_address : ""
}

output "lightsail_private_key" {
  description = "Chave privada SSH para acessar a instância via ssh -i <key> ubuntu@<ip>"
  value       = var.lightsail_enabled ? aws_lightsail_key_pair.filmbot[0].private_key : ""
  sensitive   = true
}

output "lightsail_agent_access_key_id" {
  description = "AWS_ACCESS_KEY_ID para o arquivo .env na instância"
  value       = aws_iam_access_key.lightsail_agent.id
  sensitive   = true
}

output "lightsail_agent_secret_access_key" {
  description = "AWS_SECRET_ACCESS_KEY para o arquivo .env na instância"
  value       = aws_iam_access_key.lightsail_agent.secret
  sensitive   = true
}
