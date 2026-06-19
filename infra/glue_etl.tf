# =============================================================================
# glue_etl.tf — Job Glue ETL PythonShell (SOR → SOT)
# =============================================================================

resource "aws_glue_job" "etl_job_pythonshell" {
  name                    = local.envs.glue_etl_job_name
  description             = "Lê JSON do SOR, transforma em Parquet no SOT e aciona os jobs Details e DQ"
  role_arn                = aws_iam_role.glue_etl_role.arn
  job_run_queuing_enabled = true
  max_retries             = 0
  timeout                 = 15
  max_capacity            = local.pythonshell_min_capacity

  command {
    # Caminho no S3 para o script principal do job.
    # O Glue baixa e executa este arquivo quando o job inicia.
    script_location = "s3://${local.envs.s3_bucket_aux}/${local.tmdb_prefix}/${local.envs.glue_etl_job_name}/app/main.py"
    name            = "pythonshell"
    python_version  = "3.9"
  }

  notification_property {
    notify_delay_after = 3 # Envia notificação de "job demorado" após 3 minutos
  }

  default_arguments = {
    "--job-language" = "python"

    # ==========================================================================
    # --extra-py-files: Adiciona módulos Python ao sys.path do job
    # ==========================================================================
    # Por que usar .whl em vez de .zip?
    # Jobs PythonShell aceitam apenas .whl ou .egg em --extra-py-files.
    # Arquivos .zip são suportados apenas em jobs Spark.
    # O arquivo .whl contém o pacote "src" (src/utils.py, etc.) da aplicação,
    # permitindo que o main.py faça "from src.utils import ..." sem erro.
    "--extra-py-files" = "s3://${local.envs.s3_bucket_aux}/${local.tmdb_prefix}/${local.envs.glue_etl_job_name}/${local.glue_etl_wheel_filename}"

    # ==========================================================================
    # --additional-python-modules: Instala bibliotecas PyPI no runtime do Glue
    # ==========================================================================
    # O Glue não tem todas as bibliotecas pré-instaladas. Esta opção instala
    # as dependências listadas no requirements.txt durante a inicialização do job.
    # O valor é uma string CSV: "boto3,pandas,awswrangler" (gerado pelo locals.tf)
    "--additional-python-modules" = local.glue_etl_additional_python_modules

    # Prefixo dos grupos de log no CloudWatch para este job específico.
    # Cria: /{nome-do-job}/error e /{nome-do-job}/output
    "--custom-logGroup-prefix" = "/${local.envs.glue_etl_job_name}"

    # ==========================================================================
    # ARGUMENTOS ESTÁTICOS — Configurações fixas do job
    # ==========================================================================
    # Estes valores são os mesmos em toda execução do job.
    # Argumentos dinâmicos (TABLE_TYPE, MEDIA_TYPE, YEAR, etc.) são passados
    # pela Lambda a cada chamada StartJobRun — cada execução pode ter valores
    # diferentes para processar um tipo/ano específico.
    "--S3_BUCKET_SOR"              = local.envs.s3_bucket_sor              # Onde ler os dados brutos
    "--S3_BUCKET_SOT"              = local.envs.s3_bucket_sot              # Onde gravar os dados processados
    "--GLUE_DATA_QUALITY_JOB_NAME" = local.envs.glue_data_quality_job_name # Nome do próximo job (validação)
    "--GLUE_AGG_JOB_NAME"          = local.envs.glue_agg_job_name          # Nome do job de agregação
    "--GLUE_DETAILS_JOB_NAME"      = local.envs.glue_details_job_name      # Nome do job de enriquecimento
    "--ENVIRONMENT"                = var.env                               # "dev" ou "prod"
  }

  tags = local.component_tags.glue_etl

  # Garante que todos os artefatos e permissões existam antes de criar o job.
  # Sem depends_on, o Terraform poderia tentar criar o job antes do script existir no S3.
  depends_on = [
    aws_s3_object.deploy_scripts_bucket_etl,
    aws_s3_object.deploy_app_wheel_etl,
    aws_iam_role_policy_attachment.glue_etl_base,
    aws_iam_role_policy_attachment.glue_etl_read_code,
    aws_iam_role_policy.glue_etl_logs,
    aws_iam_role_policy.glue_etl_sor_sot,
    aws_iam_role_policy.glue_etl_catalog,
    aws_glue_job.data_quality_job,
    aws_glue_job.agg_job_pythonshell,
    aws_glue_job.details_job_pythonshell,
    aws_cloudwatch_log_group.glue_etl_error,
    aws_cloudwatch_log_group.glue_etl_output
  ]

  # Permite até 10 execuções simultâneas do mesmo job.
  # Necessário pois a Lambda dispara múltiplas tabelas em paralelo:
  # (discover_movie_2022, discover_movie_2023, discover_movie_2024...)
  execution_property {
    max_concurrent_runs = 10
  }
}


# =============================================================================
# Deploy do Script Principal (main.py) para o S3
# =============================================================================
# O Glue não executa código do repositório Git diretamente.
# O script precisa estar acessível via URL S3.
# "etag" garante re-upload apenas quando o arquivo mudar (hash MD5 comparado).
# =============================================================================
resource "aws_s3_object" "deploy_scripts_bucket_etl" {
  bucket     = aws_s3_bucket.auxiliary_bucket.id
  key        = "${local.tmdb_prefix}/${local.envs.glue_etl_job_name}/app/main.py"
  source     = "${local.glue_etl_src_path}/main.py"
  etag       = filemd5("${local.glue_etl_src_path}/main.py")
  tags       = local.component_tags.glue_etl
  depends_on = [aws_s3_bucket.auxiliary_bucket]
}


# =============================================================================
# Build do Wheel Python (src/) para o S3
# =============================================================================
# O pacote "src" (src/utils.py) precisa ser empacotado como .whl para
# que o main.py possa importar "from src.utils import ..." no Glue PythonShell.
#
# Padrão igual ao usado em glue_agg.tf e glue_details.tf: o "source_hash" é
# calculado a partir do hash dos arquivos .py de origem (sempre presentes no
# checkout), e NÃO via filemd5() sobre o .whl já construído. Isso é essencial
# porque "terraform validate"/"plan" avaliam essa expressão antes de qualquer
# apply — um filemd5() sobre o wheel quebraria workflows que só validam o
# código (ex.: 03_pr_auto.yml), que não constroem o artefato.
#
# O "null_resource" abaixo executa o build localmente; seu provisioner
# "local-exec" só roda durante o "apply" (não em validate/plan), então não
# exige o wheel pronto de antemão. Como reforço extra, o CI
# (.github/workflows/02_terraform.yml) também builda o wheel antes do
# "terraform plan", garantindo que o arquivo exista mesmo se o Terraform
# state considerar o build "já feito" (triggers inalterados) em um runner
# novo onde o arquivo local não existe.
# =============================================================================
resource "null_resource" "glue_etl_wheel_build" {
  triggers = {
    source_hash  = sha256(join("", [for f in fileset(local.glue_etl_src_path, "src/**/*.py") : filesha256("${local.glue_etl_src_path}/${f}")]))
    builder_hash = filesha256("${path.module}/scripts/build_glue_wheel.py")
  }

  provisioner "local-exec" {
    command = "python ${path.module}/scripts/build_glue_wheel.py --src ${local.glue_etl_src_path} --dest ${local.glue_etl_wheel_build_path} --name glue_etl_src"
  }
}

resource "aws_s3_object" "deploy_app_wheel_etl" {
  bucket      = aws_s3_bucket.auxiliary_bucket.id
  key         = "${local.tmdb_prefix}/${local.envs.glue_etl_job_name}/${local.glue_etl_wheel_filename}"
  source      = "${local.glue_etl_wheel_build_path}/${local.glue_etl_wheel_filename}"
  source_hash = null_resource.glue_etl_wheel_build.triggers.source_hash
  tags        = local.component_tags.glue_etl
  depends_on  = [null_resource.glue_etl_wheel_build, aws_s3_bucket.auxiliary_bucket]
}
