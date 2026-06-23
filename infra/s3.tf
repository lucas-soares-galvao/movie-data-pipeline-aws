# =============================================================================
# s3.tf — Buckets da arquitetura medallion (AUX, TEMP, SOR, SOT, SPEC, DQ)
# =============================================================================
# Legenda das camadas:
#   AUX  = Auxiliar        — código Python, pacotes Lambda/Glue (.whl, .zip)
#   TEMP = Temporário      — resultados temporários do Athena (expiram em 1 dia)
#   SOR  = Source of Record — dados brutos JSON coletados da API TMDB pela Lambda
#   SOT  = Source of Truth  — dados processados em Parquet pelo Glue ETL/Details
#   SPEC = Specialized      — tabela unificada para consumo pelo FilmBot via Athena
#   DQ   = Data Quality     — resultados de validação de qualidade dos dados
# =============================================================================

resource "aws_s3_bucket" "auxiliary_bucket" {
  bucket        = local.envs.s3_bucket_aux
  force_destroy = true
  tags          = local.component_tags.shared
  depends_on    = [terraform_data.cicd_policies_ready]
}

# Bloqueia qualquer forma de acesso público a este bucket.
# Todos os 4 flags são necessários para cobertura completa:
# - block_public_acls       → Bloqueia novas ACLs públicas
# - block_public_policy     → Bloqueia políticas que concedam acesso público
# - ignore_public_acls      → Ignora ACLs públicas já existentes
# - restrict_public_buckets → Restringe acesso a bucket já público
resource "aws_s3_bucket_public_access_block" "auxiliary_bucket" {
  bucket                  = aws_s3_bucket.auxiliary_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Ativa criptografia AES256 para todos os objetos armazenados.
# AES256 é o padrão de criptografia gerenciado pela própria AWS (SSE-S3).
# Alternativa seria SSE-KMS (com chave gerenciada pelo usuário), mais controlada
# mas com custo adicional por chamada de API de criptografia.
resource "aws_s3_bucket_server_side_encryption_configuration" "auxiliary_bucket" {
  bucket = aws_s3_bucket.auxiliary_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Política de ciclo de vida para otimização de custo:
# - "abort_incomplete_multipart_upload" → Cancela uploads em partes que ficaram
#   pendentes por mais de 7 dias (evita cobranças de uploads incompletos)
# - "transition STANDARD_IA" após 30 dias → Move objetos para armazenamento
#   "Infrequent Access" (IA), ~60% mais barato, ideal para arquivos raramente acessados
resource "aws_s3_bucket_lifecycle_configuration" "auxiliary_bucket_lifecycle" {
  bucket = aws_s3_bucket.auxiliary_bucket.id

  rule {
    id     = "cost-optimization"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

# Política que NEGA qualquer acesso sem HTTPS (TLS).
# "aws:SecureTransport = false" = a conexão NÃO usa SSL/TLS.
# "Effect = Deny" + esta condição = bloqueia conexões HTTP não criptografadas.
# Isso protege os dados em trânsito entre clientes e o S3.
resource "aws_s3_bucket_policy" "auxiliary_bucket_ssl" {
  bucket = aws_s3_bucket.auxiliary_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonSSL"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.auxiliary_bucket.arn,
        "${aws_s3_bucket.auxiliary_bucket.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}


# =============================================================================
# BUCKET TEMP — Resultados Temporários do Athena
# =============================================================================
resource "aws_s3_bucket" "temporary_bucket" {
  bucket        = local.envs.s3_bucket_temp
  force_destroy = true
  tags          = local.component_tags.glue_agg
  depends_on    = [terraform_data.cicd_policies_ready]
}

resource "aws_s3_bucket_public_access_block" "temporary_bucket" {
  bucket                  = aws_s3_bucket.temporary_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "temporary_bucket" {
  bucket = aws_s3_bucket.temporary_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Resultados do Athena são descartados após 1 dia — sem valor de longo prazo.
resource "aws_s3_bucket_lifecycle_configuration" "temporary_bucket_lifecycle" {
  bucket = aws_s3_bucket.temporary_bucket.id

  rule {
    id     = "delete-after-1-day"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    expiration {
      days = 1 # Deleta automaticamente após 1 dia
    }
  }
}

resource "aws_s3_bucket_policy" "temporary_bucket_ssl" {
  bucket = aws_s3_bucket.temporary_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonSSL"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.temporary_bucket.arn,
        "${aws_s3_bucket.temporary_bucket.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}


# =============================================================================
# BUCKET SOR — Source of Record (Dados Brutos)
# =============================================================================
resource "aws_s3_bucket" "sor_bucket" {
  bucket        = local.envs.s3_bucket_sor
  force_destroy = true
  tags          = local.component_tags.lambda_api
  depends_on    = [terraform_data.cicd_policies_ready]
}

resource "aws_s3_bucket_public_access_block" "sor_bucket" {
  bucket                  = aws_s3_bucket.sor_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sor_bucket" {
  bucket = aws_s3_bucket.sor_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Dados brutos são sobrescritos semanalmente pela Lambda, então o histórico
# de mais de 30 dias vai para STANDARD_IA (mais barato, raramente acessado).
resource "aws_s3_bucket_lifecycle_configuration" "sor_bucket_lifecycle" {
  bucket = aws_s3_bucket.sor_bucket.id

  rule {
    id     = "cost-optimization"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

resource "aws_s3_bucket_policy" "sor_bucket_ssl" {
  bucket = aws_s3_bucket.sor_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonSSL"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.sor_bucket.arn,
        "${aws_s3_bucket.sor_bucket.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}


resource "aws_s3_bucket" "sot_bucket" {
  bucket        = local.envs.s3_bucket_sot
  force_destroy = true
  tags          = local.component_tags.glue_etl
  depends_on    = [terraform_data.cicd_policies_ready]
}

resource "aws_s3_bucket_public_access_block" "sot_bucket" {
  bucket                  = aws_s3_bucket.sot_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sot_bucket" {
  bucket = aws_s3_bucket.sot_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 90 dias antes de mover para STANDARD_IA — dados históricos de múltiplos anos
# têm valor de longo prazo para análises e comparações temporais.
resource "aws_s3_bucket_lifecycle_configuration" "sot_bucket_lifecycle" {
  bucket = aws_s3_bucket.sot_bucket.id

  rule {
    id     = "cost-optimization"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
  }
}

resource "aws_s3_bucket_policy" "sot_bucket_ssl" {
  bucket = aws_s3_bucket.sot_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonSSL"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.sot_bucket.arn,
        "${aws_s3_bucket.sot_bucket.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}


# =============================================================================
# BUCKET SPEC — Specialized (Tabela Final para o FilmBot)
# =============================================================================
resource "aws_s3_bucket" "spec_bucket" {
  bucket        = local.envs.s3_bucket_spec
  force_destroy = true
  tags          = local.component_tags.glue_agg
  depends_on    = [terraform_data.cicd_policies_ready]
}

resource "aws_s3_bucket_public_access_block" "spec_bucket" {
  bucket                  = aws_s3_bucket.spec_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "spec_bucket" {
  bucket = aws_s3_bucket.spec_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "spec_bucket_lifecycle" {
  bucket = aws_s3_bucket.spec_bucket.id

  rule {
    id     = "cost-optimization"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
  }
}

resource "aws_s3_bucket_policy" "spec_bucket_ssl" {
  bucket = aws_s3_bucket.spec_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonSSL"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.spec_bucket.arn,
        "${aws_s3_bucket.spec_bucket.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}


# =============================================================================
# BUCKET DATA QUALITY — Resultados de Qualidade de Dados
# =============================================================================
resource "aws_s3_bucket" "data_quality_bucket" {
  bucket        = local.envs.s3_bucket_data_quality
  force_destroy = true
  tags          = local.component_tags.glue_data_quality
  depends_on    = [terraform_data.cicd_policies_ready]
}

resource "aws_s3_bucket_public_access_block" "data_quality_bucket" {
  bucket                  = aws_s3_bucket.data_quality_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_quality_bucket" {
  bucket = aws_s3_bucket.data_quality_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data_quality_bucket_lifecycle" {
  bucket = aws_s3_bucket.data_quality_bucket.id

  rule {
    id     = "cost-optimization"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

resource "aws_s3_bucket_policy" "data_quality_bucket_ssl" {
  bucket = aws_s3_bucket.data_quality_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonSSL"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.data_quality_bucket.arn,
        "${aws_s3_bucket.data_quality_bucket.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}
