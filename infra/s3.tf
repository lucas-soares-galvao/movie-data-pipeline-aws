# Raciocinio: provisiona buckets por funcao (codigo, temporario, SOR, SOT, spec, DQ) para separar responsabilidades.

resource "aws_s3_bucket" "auxiliary_bucket" {
  bucket = local.envs.s3_bucket_aux
  force_destroy = true
}


# Bucket temporario para objetos do Athena, com politica de expiracao de 1 dia.
resource "aws_s3_bucket" "temporary_bucket" {
  bucket = local.envs.s3_bucket_temp
  force_destroy = true
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


# Bucket principal para dados de entrada/saida processados pela Lambda.
resource "aws_s3_bucket" "sor_bucket" {
  bucket = local.envs.s3_bucket_sor
  force_destroy = true
}


# Bucket principal para dados de entrada/saida processados pelo Glue ETL.
resource "aws_s3_bucket" "sot_bucket" {
  bucket = local.envs.s3_bucket_sot
  force_destroy = true
}


# Bucket principal para dados de entrada/saida processados pelo Glue ETL.
resource "aws_s3_bucket" "spec_bucket" {
  bucket = local.envs.s3_bucket_spec
  force_destroy = true
}


# Bucket principal para dados de entrada/saida processados pelo Glue ETL.
resource "aws_s3_bucket" "data_quality_bucket" {
  bucket = local.envs.s3_bucket_data_quality
  force_destroy = true
}
