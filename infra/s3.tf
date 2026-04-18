# Bucket auxiliar para códigos em python.
resource "aws_s3_bucket" "bucket_aux" {
  bucket = var.s3_bucket_aux
}

# Bucket principal para dados de entrada/saida processados pela Lambda.
resource "aws_s3_bucket" "bucket_sor" {
  bucket = var.s3_bucket_sor
}

# Bucket principal para dados de entrada/saida processados pelo Glue ETL.
resource "aws_s3_bucket" "bucket_sot" {
  bucket = var.s3_bucket_sot
}

# Bucket principal para dados de entrada/saida processados pela Glue ETL.
resource "aws_s3_bucket" "bucket_spec" {
  bucket = var.s3_bucket_spec
}
