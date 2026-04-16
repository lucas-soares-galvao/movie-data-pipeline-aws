# Bucket principal para dados de entrada/saida processados pelo Glue.
resource "aws_s3_bucket" "bucket_sot" {
  bucket = var.s3_bucket_sot
}
