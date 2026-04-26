
# Auxiliary bucket for Python code.
resource "aws_s3_bucket" "auxiliary_bucket" {
  bucket = var.s3_bucket_aux
}


# Temporary bucket for Athena objects, with 1-day expiration policy.
resource "aws_s3_bucket" "temporary_bucket" {
  bucket = var.s3_bucket_temp
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


# Main bucket for input/output data processed by Lambda.
resource "aws_s3_bucket" "sor_bucket" {
  bucket = var.s3_bucket_sor
}


# Main bucket for input/output data processed by Glue ETL.
resource "aws_s3_bucket" "sot_bucket" {
  bucket = var.s3_bucket_sot
}


# Main bucket for input/output data processed by Glue ETL.
resource "aws_s3_bucket" "spec_bucket" {
  bucket = var.s3_bucket_spec
}
