# Raciocinio: provisiona buckets por funcao (codigo, temporario, SOR, SOT, spec, DQ) para separar responsabilidades.
# Criptografia AES256 e bloqueio de acesso publico sao aplicados em todos os buckets por seguranca.
# O bloco public_access garante que nenhum dado seja exposto acidentalmente na internet.

# --------------------------------------------------------------------------
# Modulo auxiliar para armazenar scripts e artefatos de codigo (zips, main.py)
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "auxiliary_bucket" {
  bucket = local.envs.s3_bucket_aux
  force_destroy = true
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


# --------------------------------------------------------------------------
# Bucket temporario para resultados de queries do Athena.
# Objetos expiram automaticamente apos 1 dia para controle de custo.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "temporary_bucket" {
  bucket = local.envs.s3_bucket_temp
  force_destroy = true
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

    expiration {
      days = 1
    }
  }
}


# --------------------------------------------------------------------------
# Bucket SOR (System of Record) — dados brutos recebidos da Lambda/API TMDB.
# Nenhuma transformacao e feita aqui; e a "fonte da verdade" dos dados originais.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "sor_bucket" {
  bucket = local.envs.s3_bucket_sor
  force_destroy = true
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


# --------------------------------------------------------------------------
# Bucket SOT (System of Truth) — dados transformados e organizados pelo Glue ETL.
# Formato Parquet particionado por ano; consultado pelo Athena e Glue AGG.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "sot_bucket" {
  bucket = local.envs.s3_bucket_sot
  force_destroy = true
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


# --------------------------------------------------------------------------
# Bucket SPEC (Specialized) — dados agregados e unificados pelo Glue AGG.
# Contem a visao final pronta para consumo por ferramentas de BI/analytics.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "spec_bucket" {
  bucket = local.envs.s3_bucket_spec
  force_destroy = true
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


# --------------------------------------------------------------------------
# Bucket Data Quality — resultados das verificacoes de qualidade de dados.
# Permite auditoria e rastreabilidade das regras aplicadas pelo Glue DQ.
# --------------------------------------------------------------------------
resource "aws_s3_bucket" "data_quality_bucket" {
  bucket = local.envs.s3_bucket_data_quality
  force_destroy = true
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
