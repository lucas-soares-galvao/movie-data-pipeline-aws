# Raciocinio: cria roles e anexos para separar responsabilidades e aplicar menor privilegio.

resource "aws_iam_role" "lambda_function" {
  name = "${local.envs.lambda_api_name}-function"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# Raciocinio: nao usa AWSLambdaBasicExecutionRole pois ela concede logs:CreateLogGroup,
# o que permitiria a Lambda criar um grupo de logs sem retencao fora do controle do Terraform.
# A policy abaixo permite apenas escrever logs no grupo pre-existente criado pelo Terraform.
resource "aws_iam_role_policy" "lambda_logs" {
  name = "${local.envs.lambda_api_name}-logs"
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
        "arn:aws:logs:*:*:log-group:/aws/lambda/${local.envs.lambda_api_name}",
        "arn:aws:logs:*:*:log-group:/aws/lambda/${local.envs.lambda_api_name}:log-stream:*",
      ]
    }]
  })
}

# =========================
# GLUE ETL ROLE
# =========================
resource "aws_iam_role" "glue_etl_role" {
  name = "${local.envs.iam_role_glue}-etl"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_etl_service_role" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}


# =========================
# GLUE DATA QUALITY ROLE
# =========================
resource "aws_iam_role" "glue_dq_role" {
  name = "${local.envs.iam_role_glue}-dq"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_dq_service_role" {
  role       = aws_iam_role.glue_dq_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# =========================
# GLUE AGG ROLE
# =========================
resource "aws_iam_role" "glue_agg_role" {
  name = "${local.envs.iam_role_glue}-agg"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_agg_service_role" {
  role       = aws_iam_role.glue_agg_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy_attachment" "glue_agg_read_code" {
  role       = aws_iam_role.glue_agg_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}
