# IAM role for Glue jobs
resource "aws_iam_role" "glue_job_role" {
  count = var.create_role ? 1 : 0
  name  = var.iam_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "glue.amazonaws.com"
        }
      }
    ]
  })

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_role" "glue_job_role" {
  count = var.create_role ? 0 : 1
  name  = var.iam_role_name
}

resource "aws_iam_role_policy_attachment" "glue_service_role" {
  role       = local.glue_role_name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_read_code_from_s3" {
  name = "${var.iam_role_name}-read-code"
  role = local.glue_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListCodePrefix"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = ["arn:aws:s3:::${var.s3_bucket_aux}"]
        Condition = {
          StringLike = {
            "s3:prefix" = ["glue/${var.env}/*"]
          }
        }
      },
      {
        Sid    = "ReadGlueArtifacts"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_aux}/glue/${var.env}/*"
        ]
      }
    ]
  })
}