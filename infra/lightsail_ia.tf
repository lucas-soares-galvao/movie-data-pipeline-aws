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
        Resource = "*"
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
        ]
        Resource = "*"
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
  provider = aws.lightsail
  name     = "filmbot-key-${var.env}"
  tags     = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

# ── Lightsail: instância ──────────────────────────────────────────────────────

resource "aws_lightsail_instance" "filmbot" {
  provider          = aws.lightsail
  name              = "${var.lightsail_instance_name}-${var.env}"
  availability_zone = "us-east-1a"
  blueprint_id      = "ubuntu_22_04"
  bundle_id         = "micro_3_0" # 1 GB RAM, 1 vCPU, 40 GB SSD — $5/mês
  key_pair_name     = aws_lightsail_key_pair.filmbot.name
  tags              = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

# ── Lightsail: abertura de portas ─────────────────────────────────────────────

resource "aws_lightsail_instance_public_ports" "filmbot" {
  provider      = aws.lightsail
  instance_name = aws_lightsail_instance.filmbot.name

  port_info {
    from_port = 22
    to_port   = 22
    protocol  = "tcp"
  }

  port_info {
    from_port = 8501
    to_port   = 8501
    protocol  = "tcp"
  }
}

# ── Lightsail: IP estático ────────────────────────────────────────────────────

resource "aws_lightsail_static_ip" "filmbot" {
  provider = aws.lightsail
  name     = "filmbot-static-ip-${var.env}"
}

resource "aws_lightsail_static_ip_attachment" "filmbot" {
  provider       = aws.lightsail
  static_ip_name = aws_lightsail_static_ip.filmbot.name
  instance_name  = aws_lightsail_instance.filmbot.name
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "lightsail_public_ip" {
  description = "IP público fixo da instância Lightsail — acesse http://<ip>:8501"
  value       = aws_lightsail_static_ip.filmbot.ip_address
}

output "lightsail_private_key" {
  description = "Chave privada SSH para acessar a instância via ssh -i <key> ubuntu@<ip>"
  value       = aws_lightsail_key_pair.filmbot.private_key
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
