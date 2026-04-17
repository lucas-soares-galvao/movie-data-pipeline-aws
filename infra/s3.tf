# Bucket auxiliar para códigos em python.
resource "aws_s3_bucket" "bucket_aux" {
  bucket = var.s3_bucket_aux
}

# Bucket principal para dados de entrada/saida processados pelo Glue.
resource "aws_s3_bucket" "bucket_sor" {
  bucket = var.s3_bucket_sor
}