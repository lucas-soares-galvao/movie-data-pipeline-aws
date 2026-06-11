# =============================================================================
# ARQUIVO: lambda_api.tf — Função AWS Lambda (Coleta de Dados da API TMDB)
# =============================================================================
#
# O QUE É AWS LAMBDA?
# Lambda é o serviço de computação "serverless" (sem servidor) da AWS.
# Você só paga pelo tempo que o código está executando — quando não está
# rodando, não há custo de servidor.
#
# ANALOGIA: Como um táxi vs. um carro próprio. Ter um servidor sempre
# ligado é como ter um carro parado na garagem (pagando seguro mesmo sem usar).
# Lambda é como chamar um táxi: você paga só pela viagem.
#
# FUNÇÃO DESTA LAMBDA:
# 1. É disparada pelo EventBridge (agendador) diariamente
# 2. Busca dados de filmes e séries na API do TMDB (paginando todos os resultados)
# 3. Salva os dados brutos em JSON no bucket S3 SOR
# 4. Dispara os jobs Glue ETL para processar os dados
#
# FLUXO DE DEPLOY DA LAMBDA:
# código Python → build_lambda_package.py → .zip local → S3 AUX → Lambda
# O hash do .zip é comparado na próxima execução — se não mudou, não re-deploya.
# =============================================================================

# =============================================================================
# PASSO 1: Construir o Pacote Python (.zip) da Lambda
# =============================================================================
# "null_resource" é um recurso especial do Terraform que não cria nada na AWS.
# É usado para executar comandos locais (local-exec) como parte do processo.
#
# "triggers" define quando este recurso deve ser re-executado:
# - source_hash: hash de todos os arquivos .py (se qualquer código mudar)
# - requirements_hash: hash do requirements.txt (se dependências mudarem)
# - builder_hash: hash do script de build (se o próprio builder mudar)
#
# Se nenhum desses hashes mudar entre dois "terraform apply", o build
# NÃO é reexecutado (evita repackaging desnecessário).
#
# "provisioner local-exec" executa um comando no computador local (não na AWS):
# Chama build_lambda_package.py que instala dependências e cria o .zip.
# =============================================================================
resource "null_resource" "lambda_build" {
  triggers = {
    source_hash       = sha256(join("", [for f in fileset(local.lambda_api_src_path, "**/*.py") : filesha256("${local.lambda_api_src_path}/${f}")]))
    requirements_hash = filesha256(local.lambda_api_requirements_path)
    builder_hash      = filesha256("${path.module}/scripts/build_lambda_package.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_lambda_package.py --src ${local.lambda_api_src_path} --requirements ${local.lambda_api_requirements_path} --dest ${local.lambda_api_build_path}"
  }
}

# =============================================================================
# PASSO 2: Criar o Arquivo .zip a partir da Pasta de Build
# =============================================================================
# "archive_file" é um data source do provider Archive.
# Ele comprime a pasta de build em um arquivo .zip que pode ser enviado à AWS.
#
# "depends_on" garante que o build (passo 1) terminou antes de criar o .zip.
# "output_path" é onde o arquivo .zip será salvo localmente.
# =============================================================================
data "archive_file" "lambda_bundle" {
  type        = "zip"
  output_path = "${path.module}/lambda_bundle.zip"
  source_dir  = local.lambda_api_build_path

  depends_on = [
    null_resource.lambda_build
  ]
}

# =============================================================================
# PASSO 3: Enviar o .zip para o Bucket S3 AUX
# =============================================================================
# A Lambda é configurada para buscar seu código do S3 (não é enviado direto).
# Vantagens de usar S3:
# - Suporta pacotes maiores (250 MB vs. 50 MB no upload direto)
# - O código fica versionado e auditável no S3
# - Outros serviços podem inspecionar o código se necessário
#
# "etag" é o hash MD5 do arquivo. O S3 usa para verificar integridade
# no upload e o Terraform usa para detectar mudanças (só re-envia se mudar).
# =============================================================================
resource "aws_s3_object" "lambda_deploy_package" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.envs.lambda_api_name}/lambda_bundle.zip"
  source     = data.archive_file.lambda_bundle.output_path
  etag       = data.archive_file.lambda_bundle.output_md5
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}

# =============================================================================
# PASSO 4: Criar a Função Lambda
# =============================================================================
# Configurações da função Lambda explicadas:
#
# function_name → Nome único da função no ambiente (ex: "lambda-api-prod")
# role          → ARN da Role IAM que define o que a Lambda pode fazer
# handler       → "main.lambda_handler" = arquivo main.py, função lambda_handler()
#                 Este é o ponto de entrada da execução
# runtime       → Python 3.11 (versão suportada pelo Glue e disponível no Lambda)
# architectures → ["arm64"] = processador ARM (Graviton2)
#                 ~20% mais rápido e ~20% mais barato que x86_64 na AWS
# timeout       → 900 segundos = 15 minutos (máximo do Lambda)
#                 Necessário pois a coleta de milhares de páginas da API TMDB
#                 pode levar vários minutos
# memory_size   → 1024 MB = 1 GB de RAM
#                 Lambda aloca CPU proporcionalmente à memória — mais memória
#                 = mais CPU = execução mais rápida da coleta de dados
#
# VARIÁVEIS DE AMBIENTE (environment.variables):
# Passadas para o código Python como variáveis de ambiente (os.environ).
# - TMDB_SECRET_ARN   → Onde buscar a chave da API TMDB no Secrets Manager
# - GLUE_ETL_JOB_NAME → Qual job Glue disparar após a coleta
# - S3_BUCKET_SOR     → Onde salvar os dados brutos
# - S3_BUCKET_AUX     → Bucket de artefatos (para scripts Glue)
# - ENVIRONMENT       → "dev" ou "prod" (para lógica condicional no código)
#
# s3_bucket + s3_key   → De onde a Lambda busca seu código .zip
# source_code_hash     → Hash do .zip. Quando muda, a AWS faz re-deploy
#                        automático do código (sem precisar criar nova versão)
#
# depends_on → Garante que as policies IAM existam antes de criar a Lambda.
#              Sem isso, a Lambda poderia ser criada antes das permissões.
# =============================================================================
resource "aws_lambda_function" "simple_lambda" {
  function_name = local.envs.lambda_api_name
  role          = aws_iam_role.lambda_function.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.11"
  architectures = ["arm64"]
  timeout       = 900
  memory_size   = 1024

  environment {
    variables = {
      TMDB_SECRET_ARN   = var.tmdb_secret_arn
      GLUE_ETL_JOB_NAME = local.envs.glue_etl_job_name
      S3_BUCKET_SOR     = local.envs.s3_bucket_sor
      S3_BUCKET_AUX     = local.envs.s3_bucket_aux
      ENVIRONMENT       = var.env
    }
  }

  s3_bucket        = local.envs.s3_bucket_aux
  s3_key           = aws_s3_object.lambda_deploy_package.key
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  tags             = local.component_tags.lambda_api

  depends_on = [
    aws_iam_role_policy.lambda_logs,
    aws_iam_role_policy.lambda_start_glue_jobs,
    aws_iam_role_policy.lambda_s3_policy,
    null_resource.lambda_build,
    aws_s3_object.lambda_deploy_package,
    aws_cloudwatch_log_group.lambda_log,
    aws_iam_role_policy.lambda_secrets_manager_policy,
  ]
}
