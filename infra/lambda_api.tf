
resource "null_resource" "lambda_build" {
  triggers = {
    source_hash = sha256(join("", [for f in fileset(local.lambda_api_src_path, "**/*.py") : filesha256("${local.lambda_api_src_path}/${f}")]))
    requirements_hash = filesha256(local.lambda_api_requirements_path)
		builder_hash = filesha256("${path.module}/scripts/build_lambda_package.py")
		# CI runners are ephemeral; force rebuild so .lambda_build exists every run.
		always_run = timestamp()
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_lambda_package.py --src ${local.lambda_api_src_path} --requirements ${local.lambda_api_requirements_path} --dest ${local.lambda_api_build_path}"
  }
}

data "archive_file" "lambda_bundle" {
	type        = "zip"
	output_path = "${path.module}/lambda_bundle.zip"
	source_dir  = local.lambda_api_build_path

	depends_on = [
		null_resource.lambda_build
	]
}

resource "aws_s3_object" "lambda_deploy_package" {
	bucket = aws_s3_bucket.auxiliary_bucket.id
	key    = "${local.envs.lambda_api_name}/lambda_bundle.zip"
	source = data.archive_file.lambda_bundle.output_path
	etag   = data.archive_file.lambda_bundle.output_md5
	depends_on = [aws_s3_bucket.auxiliary_bucket]
}


resource "aws_lambda_function" "simple_lambda" {
	function_name = local.envs.lambda_api_name
	role          = aws_iam_role.lambda_function.arn
	handler       = "main.lambda_handler"
	runtime       = "python3.11"
	timeout       = 900
	memory_size   = 1024

	environment {
		variables = {
			TMDB_SECRET_ARN            = var.tmdb_secret_arn
			GLUE_ETL_JOB_NAME          = local.envs.glue_etl_job_name
			S3_BUCKET_SOR              = local.envs.s3_bucket_sor
			S3_BUCKET_AUX              = local.envs.s3_bucket_aux
			ENVIRONMENT                = var.env
		}
	}

	s3_bucket        = local.envs.s3_bucket_aux
	s3_key           = aws_s3_object.lambda_deploy_package.key
	source_code_hash = data.archive_file.lambda_bundle.output_base64sha256

	depends_on = [
		aws_iam_role_policy_attachment.lambda_basic_execution,
		aws_iam_role_policy.lambda_start_glue_jobs,
		aws_iam_role_policy.lambda_s3_policy,
		null_resource.lambda_build,
		aws_s3_object.lambda_deploy_package,
		aws_cloudwatch_log_group.lambda_log,
		aws_iam_role_policy.lambda_secrets_manager_policy,
	]
}
