# =============================================================================
# iam_roles.tf — Roles IAM dos serviços (Lambda, Glue, EventBridge, Lightsail)
# =============================================================================

resource "aws_iam_role" "lambda_function" {
  name = "${local.tmdb_prefix}-lambda-api-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  depends_on = [terraform_data.cicd_policies_ready]
}

# =============================================================================
# POLICY INLINE DE LOGS DA LAMBDA
# =============================================================================
# Permite que a Lambda grave logs no CloudWatch (essencial para monitoramento).
#
# POR QUE NÃO USAR A MANAGED POLICY "AWSLambdaBasicExecutionRole"?
# A policy gerenciada pela AWS concede "logs:CreateLogGroup", que permitiria
# à Lambda criar grupos de log sem a retenção definida pelo Terraform.
# Usando uma policy customizada, só permitimos escrever em grupos de log
# que já existem (criados pelo cloudwatch_logs.tf com retenção de 5 dias em prod).
# Isso garante controle total sobre a configuração de logs.
# =============================================================================
resource "aws_iam_role_policy" "lambda_logs" {
  name = "${local.tmdb_prefix}-lambda-api-logs-${var.env}"
  role = aws_iam_role.lambda_function.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "WriteLambdaLogs"
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = [
        "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.envs.lambda_api_name}",
        "arn:aws:logs:sa-east-1:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.envs.lambda_api_name}:log-stream:*",
      ]
    }]
  })
}

resource "aws_iam_role" "glue_etl_role" {
  name = "${local.tmdb_prefix}-glue-etl-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })

  depends_on = [terraform_data.cicd_policies_ready]
}

resource "aws_iam_role_policy_attachment" "glue_etl_base" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = aws_iam_policy.glue_shared_base.arn
}


resource "aws_iam_role" "glue_dq_role" {
  name = "${local.tmdb_prefix}-glue-data-quality-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })

  depends_on = [terraform_data.cicd_policies_ready]
}

resource "aws_iam_role_policy_attachment" "glue_dq_base" {
  role       = aws_iam_role.glue_dq_role.name
  policy_arn = aws_iam_policy.glue_shared_base.arn
}

# =============================================================================
resource "aws_iam_role" "glue_agg_role" {
  name = "${local.tmdb_prefix}-glue-agg-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })

  depends_on = [terraform_data.cicd_policies_ready]
}

resource "aws_iam_role_policy_attachment" "glue_agg_base" {
  role       = aws_iam_role.glue_agg_role.name
  policy_arn = aws_iam_policy.glue_shared_base.arn
}

resource "aws_iam_role_policy_attachment" "glue_agg_read_code" {
  role       = aws_iam_role.glue_agg_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}

resource "aws_iam_role" "glue_details_role" {
  name = "${local.tmdb_prefix}-glue-details-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })

  depends_on = [terraform_data.cicd_policies_ready]
}

resource "aws_iam_role_policy_attachment" "glue_details_base" {
  role       = aws_iam_role.glue_details_role.name
  policy_arn = aws_iam_policy.glue_shared_base.arn
}

resource "aws_iam_role_policy_attachment" "glue_details_read_code" {
  role       = aws_iam_role.glue_details_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}

resource "aws_iam_role" "sfn_backfill_role" {
  name = "${local.tmdb_prefix}-sfn-backfill-role-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })

  depends_on = [terraform_data.cicd_policies_ready]
}

resource "aws_iam_role" "eventbridge_sfn_role" {
  name = "${local.tmdb_prefix}-eventbridge-sfn-role-${var.env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
    }]
  })

  depends_on = [terraform_data.cicd_policies_ready]
}
