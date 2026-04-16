# Role principal assumida pelo servico AWS Glue durante a execucao do job.
resource "aws_iam_role" "glue_job_role" {
  name  = var.iam_role_name

  # Trust policy: permite que o servico glue.amazonaws.com assuma esta role.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "glue.amazonaws.com"
        }
      }
    ]
  })
}

# Import opcional para adotar uma role existente no estado do Terraform.
import {
  to = aws_iam_role.glue_job_role
  id = var.iam_role_name
}

# Anexa a policy gerenciada padrao da AWS necessaria para execucao do Glue.
resource "aws_iam_role_policy_attachment" "glue_service_role" {
  role       = aws_iam_role.glue_job_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# Policy customizada com permissao minima para ler scripts e bundles no S3.
resource "aws_iam_role_policy" "glue_read_code_from_s3" {
  name = "${var.iam_role_name}-read-code"
  role = aws_iam_role.glue_job_role.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListCodePrefix"
        Effect = "Allow"
        # Necessario para listar objetos dentro do bucket (escopo de prefixo abaixo).
        Action = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${var.s3_bucket_aux}"]
        Condition = {
          StringLike = {
            # Restringe a listagem apenas ao prefixo de artefatos do Glue.
            "s3:prefix" = ["glue/*"]
          }
        }
      },
      {
        Sid    = "ReadGlueArtifacts"
        Effect = "Allow"
        # Permite leitura dos arquivos publicados para execucao do job.
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = [
          # Escopo limitado aos objetos dentro do prefixo glue/ no bucket auxiliar.
          "arn:aws:s3:::${var.s3_bucket_aux}/glue/*"
        ]
      }
    ]
  })
}
