# Raciocinio: provisiona buckets por funcao (codigo, temporario, SOR, SOT, spec, DQ) para separar responsabilidades.
# Criptografia AES256 e bloqueio de acesso publico sao aplicados em todos os buckets por seguranca.
# O bloco public_access garante que nenhum dado seja exposto acidentalmente na internet.

# --------------------------------------------------------------------------
# Modulo auxiliar para armazenar scripts e artefatos de codigo (zips, main.py)
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "auxiliary_bucket" {
  bucket        = local.envs.s3_bucket_aux
  force_destroy = true
  tags          = local.component_tags.shared
}

resource "aws_s3_bucket_public_access_block" "auxiliary_bucket" {
  bucket                  = aws_s3_bucket.auxiliary_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "auxiliary_bucket" {
  bucket = aws_s3_bucket.auxiliary_bucket.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

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


# --------------------------------------------------------------------------
# Bucket temporario para resultados de queries do Athena.
# Objetos expiram automaticamente apos 1 dia para controle de custo.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "temporary_bucket" {
  bucket        = local.envs.s3_bucket_temp
  force_destroy = true
  tags          = local.component_tags.glue_agg
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

resource "aws_s3_bucket_lifecycle_configuration" "temporary_bucket_lifecycle" {
  bucket = aws_s3_bucket.temporary_bucket.id

  rule {
    id     = "delete-after-1-day"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    expiration {
      days = 1
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


# --------------------------------------------------------------------------
# Bucket SOR (System of Record) — dados brutos recebidos da Lambda/API TMDB.
# Nenhuma transformacao e feita aqui; e a "fonte da verdade" dos dados originais.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "sor_bucket" {
  bucket        = local.envs.s3_bucket_sor
  force_destroy = true
  tags          = local.component_tags.lambda_api
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


# --------------------------------------------------------------------------
# Bucket SOT (System of Truth) — dados transformados e organizados pelo Glue ETL.
# Formato Parquet particionado por ano; consultado pelo Athena e Glue AGG.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "sot_bucket" {
  bucket        = local.envs.s3_bucket_sot
  force_destroy = true
  tags          = local.component_tags.glue_etl
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


# --------------------------------------------------------------------------
# Bucket SPEC (Specialized) — dados agregados e unificados pelo Glue AGG.
# Contem a visao final pronta para consumo por ferramentas de BI/analytics.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "spec_bucket" {
  bucket        = local.envs.s3_bucket_spec
  force_destroy = true
  tags          = local.component_tags.glue_agg
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


# --------------------------------------------------------------------------
# Bucket Data Quality — resultados das verificacoes de qualidade de dados.
# Permite auditoria e rastreabilidade das regras aplicadas pelo Glue DQ.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "data_quality_bucket" {
  bucket        = local.envs.s3_bucket_data_quality
  force_destroy = true
  tags          = local.component_tags.glue_data_quality
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
