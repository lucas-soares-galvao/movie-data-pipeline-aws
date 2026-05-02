
# Auxiliary bucket for Python code.
resource "aws_s3_bucket" "auxiliary_bucket" {
  bucket = local.envs.s3_bucket_aux
  force_destroy = true
}


# Temporary bucket for Athena objects, with 1-day expiration policy.
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


# Main bucket for input/output data processed by Lambda.
resource "aws_s3_bucket" "sor_bucket" {
  bucket = local.envs.s3_bucket_sor
  force_destroy = true
}


# Main bucket for input/output data processed by Glue ETL.
resource "aws_s3_bucket" "sot_bucket" {
  bucket = local.envs.s3_bucket_sot
  force_destroy = true
}


# Main bucket for input/output data processed by Glue ETL.
resource "aws_s3_bucket" "spec_bucket" {
  bucket = local.envs.s3_bucket_spec
  force_destroy = true
}
