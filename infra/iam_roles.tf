# =============================================================================
# ARQUIVO: iam_roles.tf — Roles IAM (Identidades de Serviço AWS)
# =============================================================================
#
# O QUE É IAM?
# IAM (Identity and Access Management) é o sistema de controle de acesso da AWS.
# Tudo na AWS precisa de permissão para fazer qualquer coisa.
# Uma Lambda sem uma Role não consegue nem escrever um log.
#
# O QUE É UMA ROLE IAM?
# Uma Role é uma "identidade temporária" que um serviço AWS pode assumir.
# É diferente de um usuário (que é uma pessoa com login permanente).
#
# ANALOGIA: Imagine um funcionário de empresa terceirizada que precisa entrar
# no escritório. Em vez de dar uma chave permanente para ele, você dá um
# crachá temporário que abre apenas as portas que ele precisa.
# A Role é esse crachá temporário com acesso específico.
#
# PRINCÍPIO DO MENOR PRIVILÉGIO:
# Cada serviço recebe APENAS as permissões que precisa — nem mais, nem menos.
# A Lambda pode chamar o Glue, mas não pode deletar tabelas do Athena.
# O Glue ETL pode ler/escrever no S3, mas não pode criar Lambdas.
#
# TRUST POLICY (assume_role_policy):
# Define QUEM pode assumir esta role.
# Ex: "Service = lambda.amazonaws.com" significa "apenas o serviço Lambda
# pode usar este crachá" — humanos não podem usá-lo.
# =============================================================================

# =============================================================================
# ROLE DA LAMBDA — Identidade da Função Lambda
# =============================================================================
# Esta role permite que a função Lambda execute ações na AWS.
# As permissões específicas (o que ela pode fazer) estão em iam_policies.tf.
# Aqui apenas definimos QUEM pode assumir a role (o serviço Lambda).
# =============================================================================
resource "aws_iam_role" "lambda_function" {
  name = "${local.envs.lambda_api_name}-function"

  # Trust Policy: só o serviço Lambda da AWS pode assumir esta role
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"             # "Assumir esta identidade"
      Effect    = "Allow"                       # Permitido
      Principal = { Service = "lambda.amazonaws.com" }  # Quem pode assumir
    }]
  })
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
# que já existem (criados pelo cloudwatch_logs.tf com retenção de 30 dias).
# Isso garante controle total sobre a configuração de logs.
# =============================================================================
resource "aws_iam_role_policy" "lambda_logs" {
  name = "${local.envs.lambda_api_name}-logs"
  role = aws_iam_role.lambda_function.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "WriteLambdaLogs"
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",  # Criar fluxos de log dentro do grupo existente
        "logs:PutLogEvents",     # Escrever mensagens de log
      ]
      # Restringe ao grupo de log específico desta Lambda (não qualquer grupo)
      Resource = [
        "arn:aws:logs:*:*:log-group:/aws/lambda/${local.envs.lambda_api_name}",
        "arn:aws:logs:*:*:log-group:/aws/lambda/${local.envs.lambda_api_name}:log-stream:*",
      ]
    }]
  })
}

# =============================================================================
# ROLE DO GLUE ETL — Identidade do Job de Processamento Básico
# =============================================================================
# O Glue ETL lê JSON do SOR, transforma em Parquet e grava no SOT.
# Precisa de acesso ao S3 (leitura SOR, escrita SOT) e ao Glue Catalog.
# =============================================================================
resource "aws_iam_role" "glue_etl_role" {
  name = "${local.envs.iam_role_glue}-etl"

  # Trust Policy: só o serviço Glue pode assumir esta role
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

# "AWSGlueServiceRole" é uma policy gerenciada pela AWS que dá ao Glue
# as permissões básicas necessárias para funcionar (CloudWatch Logs,
# Glue Catalog, S3 para scripts). Permissões específicas do projeto
# (buckets SOR/SOT) são adicionadas via iam_policies.tf.
resource "aws_iam_role_policy_attachment" "glue_etl_service_role" {
  role       = aws_iam_role.glue_etl_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}


# =============================================================================
# ROLE DO GLUE DATA QUALITY — Identidade do Job de Qualidade de Dados
# =============================================================================
# O Glue DQ lê tabelas do Catalog, avalia regras e grava resultados no S3 DQ.
# É um job Spark (mais pesado que PythonShell) — precisa de mais permissões.
# =============================================================================
resource "aws_iam_role" "glue_dq_role" {
  name = "${local.envs.iam_role_glue}-dq"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_dq_service_role" {
  role       = aws_iam_role.glue_dq_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# =============================================================================
# ROLE DO GLUE AGG — Identidade do Job de Agregação Final
# =============================================================================
# O Glue AGG executa queries Athena em dados do SOT e grava no SPEC.
# Precisa de acesso de leitura ao SOT e escrita no SPEC, além de Athena.
# =============================================================================
resource "aws_iam_role" "glue_agg_role" {
  name = "${local.envs.iam_role_glue}-agg"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_agg_service_role" {
  role       = aws_iam_role.glue_agg_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# O Glue AGG também precisa ler o código wheel do bucket AUX (scripts Glue).
# Esta policy adicional garante essa permissão específica.
resource "aws_iam_role_policy_attachment" "glue_agg_read_code" {
  role       = aws_iam_role.glue_agg_role.name
  policy_arn = aws_iam_policy.glue_shared_read_code.arn
}
