# =============================================================================
# ARQUIVO: s3.tf — Buckets S3 (Armazenamento em Nuvem)
# =============================================================================
#
# O QUE É O AWS S3?
# S3 (Simple Storage Service) é o serviço de armazenamento de arquivos da AWS.
# Pense nele como uma "pasta na nuvem" onde você pode guardar qualquer tipo de
# arquivo (JSON, Parquet, ZIP, imagens, etc.) com disponibilidade de 99.999999999%.
#
# ARQUITETURA MEDALHÃO (Medallion Architecture):
# Este projeto organiza os dados em camadas progressivas de qualidade,
# cada uma em um bucket separado:
#
#   [API TMDB]
#       │
#       ▼
#  AUX  → Artefatos de código (Lambda .zip, Glue .whl)
#  TEMP → Resultados temporários de queries Athena (descartados em 1 dia)
#  SOR  → "Source of Record": dados BRUTOS da API (JSON original, sem alteração)
#       │
#       ▼ Glue ETL transforma JSON → Parquet
#  SOT  → "Source of Truth": dados PROCESSADOS (Parquet, confiável, consultável)
#       │
#       ▼ Glue AGG une filmes+séries, traduz para PT-BR
#  SPEC → "Specialized": tabela FINAL pronta para o app FilmBot
#  DQ   → "Data Quality": resultados de regras de validação (auditoria)
#
# SEGURANÇA EM TODOS OS BUCKETS:
# - Criptografia AES256: arquivos são criptografados em repouso na AWS
# - Bloqueio de acesso público: nenhum arquivo fica acessível pela internet
# - Política SSL: rejeita conexões HTTP não criptografadas (só HTTPS/TLS)
# - Lifecycle: objetos antigos mudam para storage mais barato ou são deletados
# =============================================================================

# =============================================================================
# BUCKET AUX — Artefatos de Código
# =============================================================================
# Armazena os pacotes Python deployados na AWS:
# - lambda_bundle.zip → código da Lambda
# - *.whl → wheels Python dos jobs Glue
# - scripts/*.py → scripts de ETL
#
# "force_destroy = true" permite que o Terraform delete o bucket mesmo com
# arquivos dentro, facilitando a limpeza de ambientes dev.
# =============================================================================
resource "aws_s3_bucket" "auxiliary_bucket" {
  bucket        = local.envs.s3_bucket_aux
  force_destroy = true
  tags          = local.component_tags.shared
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
# O Amazon Athena executa queries SQL em arquivos Parquet no S3.
# Os resultados de cada query precisam ser salvos em algum lugar — este bucket.
# Como os resultados são consumidos imediatamente e descartados, eles expiram
# em 1 dia automaticamente, mantendo o custo de armazenamento próximo de zero.
# =============================================================================
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
      days = 1  # Deleta automaticamente após 1 dia
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
# BUCKET SOR — Source of Record (Fonte de Registro / Dados Brutos)
# =============================================================================
# Armazena os arquivos JSON exatamente como chegam da API do TMDB.
# NENHUMA transformação é feita aqui — é a "fotografia fiel" dos dados originais.
# Isso permite reprocessar o pipeline do zero sem precisar chamar a API novamente.
#
# Estrutura de pastas dentro do bucket:
#   discover/movie/year=2024/data.json
#   discover/tv/year=2024/data.json
#   genre/movie/data.json
#   configuration/languages/data.json
#   etc.
# =============================================================================
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

# Dados brutos são sobrescritos diariamente pela Lambda, então o histórico
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


# =============================================================================
# BUCKET SOT — Source of Truth (Fonte da Verdade / Dados Processados)
# =============================================================================
# Armazena os dados processados pelo Glue ETL em formato Parquet.
#
# O QUE É PARQUET?
# Parquet é um formato de arquivo colunar (diferente de CSV que é por linha).
# Vantagens sobre JSON:
# - ~5-10x menor em tamanho (compressão eficiente)
# - Muito mais rápido para queries (lê só as colunas necessárias)
# - Preserva os tipos de dados (int, float, date)
#
# Estrutura de tabelas registradas no Glue Catalog:
#   tb_discover_movie_tmdb/year=2024/part-0000.parquet
#   tb_genre_movie_tmdb/part-0000.parquet
#   tb_details_movie_tmdb/part-0000.parquet
#   etc.
# =============================================================================
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
# BUCKET SPEC — Specialized (Especializado / Tabela Final)
# =============================================================================
# Contém a tabela final criada pelo Glue AGG: filmes e séries unificados,
# com colunas traduzidas para português, prontos para o FilmBot consumir.
#
# É o único bucket que o app Streamlit (FilmBot) consulta via Athena.
# Particionado por media_type (movie/tv) e year (ano de lançamento).
# =============================================================================
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


# =============================================================================
# BUCKET DATA QUALITY — Resultados de Qualidade de Dados
# =============================================================================
# Armazena os resultados das avaliações de qualidade executadas pelo Glue DQ.
# Para cada tabela processada, um arquivo Parquet é salvo com:
# - rule_name: nome da regra avaliada (ex: "completeness_id")
# - outcome: "Passed" ou "Failed"
# - source_table: qual tabela foi avaliada
# - evaluated_at: quando a avaliação ocorreu
#
# Permite auditoria: "Em qual data a coluna 'vote_average' começou a ter nulos?"
# =============================================================================
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
