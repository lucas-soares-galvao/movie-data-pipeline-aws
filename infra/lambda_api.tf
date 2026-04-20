resource "aws_iam_role" "lambda_role" {
	name = "${var.lambda_api_name}-role-${var.env}"

	assume_role_policy = jsonencode({
		Version = "2012-10-17"
		Statement = [
			{
				Action = "sts:AssumeRole"
				Effect = "Allow"
				Principal = {
					Service = "lambda.amazonaws.com"
				}
			}
		]
	})
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
	role       = aws_iam_role.lambda_role.name
	policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_start_glue_jobs" {
	name = "${var.lambda_api_name}-start-glue-jobs-${var.env}"
	role = aws_iam_role.lambda_role.id

	policy = jsonencode({
		Version = "2012-10-17"
		Statement = [
			{
				Effect = "Allow"
				Action = [
					"glue:StartJobRun",
					"glue:GetJobRun"
				]
				Resource = "*"
			}
		]
	})
}

resource "aws_iam_role_policy" "lambda_s3_policy" {
	name = "${var.lambda_api_name}-s3-policy-${var.env}"
	role = aws_iam_role.lambda_role.id

	policy = jsonencode({
		Version = "2012-10-17"
		Statement = [
			{
				Effect = "Allow"
				Action = [
					"s3:PutObject",
					"s3:GetObject"
				]
				Resource = "arn:aws:s3:::${var.s3_bucket_sor}/*"
			}
		]
	})
}

resource "aws_iam_role_policy" "lambda_secrets_manager_policy" {
  name = "${var.lambda_api_name}-secrets-manager-${var.env}"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = var.tmdb_secret_arn
      }
    ]
  })
}

data "archive_file" "lambda_bundle" {
	type        = "zip"
	output_path = "${path.module}/lambda_bundle.zip"

	dynamic "source" {
		for_each = fileset(local.lambda_api_src_path, "**/*.py")
		content {
			filename = source.value
			content  = file("${local.lambda_api_src_path}/${source.value}")
		}
	}
}

resource "aws_s3_object" "lambda_deploy_package" {
	bucket = var.s3_bucket_aux
	key    = "${var.lambda_api_name}/lambda_bundle.zip"
	source = data.archive_file.lambda_bundle.output_path
	etag   = filemd5(data.archive_file.lambda_bundle.output_path)
}

resource "aws_cloudwatch_log_group" "lambda_log_group" {
	name              = "/aws/lambda/${var.lambda_api_name}"
	retention_in_days = 1
}

resource "aws_lambda_function" "simple_lambda" {
	function_name = "${var.lambda_api_name}"
	role          = aws_iam_role.lambda_role.arn
	handler       = "main.lambda_handler"
	runtime       = "python3.11"
	timeout       = 300

	environment {
		variables = {
			TMDB_SECRET_ARN 		   = var.tmdb_secret_arn
			GLUE_ETL_JOB_NAME          = var.glue_etl_job_name
			GLUE_DATA_QUALITY_JOB_NAME = var.glue_data_quality_job_name
			S3_BUCKET_SOR              = var.s3_bucket_sor
		}
	}

	s3_bucket        = var.s3_bucket_aux
	s3_key           = aws_s3_object.lambda_deploy_package.key
	source_code_hash = data.archive_file.lambda_bundle.output_base64sha256

	depends_on = [
		aws_iam_role_policy_attachment.lambda_basic_execution,
		aws_iam_role_policy.lambda_start_glue_jobs,
		aws_iam_role_policy.lambda_s3_policy,
		aws_s3_object.lambda_deploy_package,
		aws_cloudwatch_log_group.lambda_log_group,
		aws_iam_role_policy.lambda_secrets_manager_policy,
	]
}
