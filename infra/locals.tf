# =============================================================================
# locals.tf — Valores derivados e nomes de recursos centralizados
# =============================================================================

locals {

  # Capacidade mínima de DPU para jobs PythonShell (1/16 de DPU)
  pythonshell_min_capacity = 0.0625

  # Prefixo tmdb que identifica o projeto (escopo de isolamento por projeto)
  tmdb_prefix = "tmdb"

  default_resource_tags = {
    Service     = "movie-data-pipeline-aws"
    Environment = local.environment_tag_value
    FinOps      = var.finops_tag_value
  }

  component_tags = {
    shared = {
      Component = "shared"
    }
    lambda_api = {
      Component = "lambda_api"
    }
    eventbridge = {
      Component = "eventbridge"
    }
    glue_etl = {
      Component = "glue_etl"
    }
    glue_data_quality = {
      Component = "glue_data_quality"
    }
    glue_agg = {
      Component = "glue_agg"
    }
    glue_details = {
      Component = "glue_details"
    }
    glue_catalog = {
      Component = "glue_catalog"
    }
    lightsail_scheduler = {
      Component = "lightsail_scheduler"
    }
    sfn_backfill = {
      Component = "sfn_backfill"
    }
  }

  # ===========================================================================
  # VALOR DA TAG ENVIRONMENT
  # ===========================================================================
  # Converte "dev"→"Dev" e "prod"→"Prod" para exibição mais limpa nas tags.
  # A sintaxe `{...}[chave]` é um map literal com acesso por chave — equivale
  # a um switch/case em outras linguagens.
  environment_tag_value = {
    dev  = "Dev"
    prod = "Prod"
  }[lower(var.env)]

  # ===========================================================================
  # ESTADO DO EVENTBRIDGE — Habilitado apenas em produção
  # ===========================================================================
  # O EventBridge agenda a execução automática da Lambda (coleta diária de dados).
  # Em dev, desabilitamos para evitar consumo desnecessário de API e custo.
  # Em prod, ativamos para coleta automática.
  # O operador "? :" é o ternário: condição ? valor_se_true : valor_se_false
  eventbridge_schedule_state = lower(var.env) == "prod" ? "ENABLED" : "DISABLED"

  # ===========================================================================
  # CAMINHOS DOS ARQUIVOS DE CÓDIGO
  # ===========================================================================
  # Definem onde estão os arquivos Python de cada componente.
  # "path.root" = pasta raiz do módulo Terraform (a pasta "infra/")
  # "${path.root}/../app/lambda_api" = pasta "app/lambda_api" relativa à "infra/"
  #
  # Esses caminhos são usados para:
  # - Empacotar o código em .zip ou .whl
  # - Calcular hashes para detectar mudanças no código
  lambda_api_src_path          = "${path.root}/../app/${var.lambda_api_path_app}"
  lambda_api_requirements_path = "${path.root}/../app/${var.lambda_api_path_app}/requirements.txt"
  lambda_api_build_path        = "${path.module}/.lambda_build" # Pasta de output do .zip

  glue_etl_src_path          = "${path.root}/../app/${var.glue_etl_path_app}"
  glue_etl_requirements_path = "${path.root}/../app/${var.glue_etl_path_app}/requirements.txt"
  glue_etl_wheel_build_path  = "${path.module}/.glue_etl_build"
  glue_etl_wheel_filename    = "glue_etl_src-0.0.0-py3-none-any.whl" # Nome padrão de wheel Python

  glue_data_quality_src_path          = "${path.root}/../app/${var.glue_data_quality_path_app}"
  glue_data_quality_requirements_path = "${path.root}/../app/${var.glue_data_quality_path_app}/requirements.txt"

  glue_agg_src_path          = "${path.root}/../app/${var.glue_agg_path_app}"
  glue_agg_requirements_path = "${path.root}/../app/${var.glue_agg_path_app}/requirements.txt"
  glue_agg_wheel_build_path  = "${path.module}/.glue_agg_build"
  glue_agg_wheel_filename    = "glue_agg_src-0.0.0-py3-none-any.whl"

  glue_details_src_path          = "${path.root}/../app/${var.glue_details_path_app}"
  glue_details_requirements_path = "${path.root}/../app/${var.glue_details_path_app}/requirements.txt"
  glue_details_wheel_build_path  = "${path.module}/.glue_details_build"
  glue_details_wheel_filename    = "glue_details_src-0.0.0-py3-none-any.whl"

  # ===========================================================================
  # MÓDULOS PYTHON ADICIONAIS PARA OS JOBS GLUE
  # ===========================================================================
  # Jobs Glue Python Shell permitem instalar dependências extras via
  # "--additional-python-modules" (uma lista separada por vírgulas).
  #
  # Este bloco lê o arquivo requirements.txt de cada job e converte em
  # uma string separada por vírgulas, ignorando linhas vazias e comentários.
  #
  # Exemplo: "boto3,pandas,awswrangler" (o que o Glue vai instalar ao iniciar)
  #
  # Sintaxe explicada:
  # - file(caminho)      → lê o conteúdo do arquivo como string
  # - split("\n", texto) → divide em lista de linhas
  # - for linha in lista : valor if condição → list comprehension (filtra e transforma)
  # - trimspace(linha)   → remove espaços em branco nas bordas
  # - join(",", lista)   → junta a lista em uma string separada por vírgulas
  glue_etl_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_etl_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])

  glue_data_quality_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_data_quality_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])

  glue_agg_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_agg_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])

  glue_details_additional_python_modules = join(",", [
    for line in split("\n", file(local.glue_details_requirements_path)) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#")
  ])

  # ===========================================================================
  # TEMPLATES DE MENSAGENS DE ALARME
  # ===========================================================================
  # Quando um alarme do CloudWatch dispara (ex: Lambda falhou), ele envia
  # uma mensagem via SNS (email). Esses templates definem o formato da mensagem.
  #
  # "<<-EOT ... EOT" é um heredoc: permite escrever strings multi-linha.
  # Os placeholders (<alarm_name>, <state>, etc.) são preenchidos pelo
  # CloudWatch automaticamente em tempo de execução.
  #
  # Um email de alerta terá este formato:
  # "[Pipeline Falha]
  #  Etapa: Lambda
  #  Alarme: nome-do-alarme
  #  Estado: ALARM
  #  Motivo: Threshold ultrapassado
  #  ..."
  lambda_alarm_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Lambda\nAlarme: <alarm_name>\nEstado: <state>\nMotivo: <reason>\nRegião: <region>\nHorário: <timestamp>"}
EOT

  eventbridge_alarm_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: EventBridge\nAlarme: <alarm_name>\nEstado: <state>\nMotivo: <reason>\nRegião: <region>\nHorário: <timestamp>"}
EOT

  glue_etl_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Glue ETL\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_data_quality_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Glue Data Quality\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_agg_succeeded_input_template = <<-EOT
{"message":"[Pipeline Sucesso Final]\nEtapa final: Glue AGG\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_agg_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Glue AGG\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  glue_details_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Glue Details\nJob: <job_name>\nStatus: <state>\nRunId: <job_run_id>\nMotivo: <reason>\nRegião: <region>\nHorário: <event_time>"}
EOT

  sfn_backfill_failed_input_template = <<-EOT
{"message":"[Pipeline Falha]\nEtapa: Step Functions Backfill\nState Machine: <state_machine>\nStatus: <status>\nExecução: <execution_arn>\nMotivo: <cause>\nRegião: <region>\nHorário: <event_time>"}
EOT

  # ===========================================================================
  # NOMES DE RECURSOS COM SUFIXO DE AMBIENTE
  # ===========================================================================
  # Todos os recursos AWS recebem "-dev" ou "-prod" no final do nome.
  # Isso garante isolamento total: recursos de dev nunca interferem em prod.
  #
  # Exemplo: "glue-etl-dev" e "glue-etl-prod" são jobs separados na AWS.
  #
  # O map "envs" centraliza esses nomes para evitar repetição nos outros arquivos.
  # Em vez de escrever "${var.glue_etl_job_name}-${var.env}" em cada arquivo,
  # usamos "local.envs.glue_etl_job_name".
  envs = {
    glue_etl_job_name          = "${local.tmdb_prefix}-${var.glue_etl_job_name}-${var.env}"
    glue_data_quality_job_name = "${local.tmdb_prefix}-${var.glue_data_quality_job_name}-${var.env}"
    glue_agg_job_name          = "${local.tmdb_prefix}-${var.glue_agg_job_name}-${var.env}"
    glue_details_job_name      = "${local.tmdb_prefix}-${var.glue_details_job_name}-${var.env}"
    lambda_api_name            = "${local.tmdb_prefix}-${var.lambda_api_name}-${var.env}"
    iam_role_glue              = "${local.tmdb_prefix}-${var.iam_role_glue}-${var.env}"
    iam_role_lambda            = "${local.tmdb_prefix}-${var.iam_role_lambda}-${var.env}"
    s3_bucket_aux              = "${var.s3_bucket_aux}-${var.env}"
    s3_bucket_temp             = "${var.s3_bucket_temp}-${var.env}"
    s3_bucket_sor              = "${var.s3_bucket_sor}-${var.env}"
    s3_bucket_sot              = "${var.s3_bucket_sot}-${var.env}"
    s3_bucket_spec             = "${var.s3_bucket_spec}-${var.env}"
    s3_bucket_data_quality     = "${var.s3_bucket_data_quality}-${var.env}"

    # Glue Catalog — Databases
    glue_catalog_db_movie   = "db_${local.tmdb_prefix}_movie_${var.env}"
    glue_catalog_db_tv      = "db_${local.tmdb_prefix}_tv_${var.env}"
    glue_catalog_db_unified = "db_${local.tmdb_prefix}_unified_${var.env}"

    # Glue Catalog — Tables
    glue_catalog_tb_discover_movie            = "tb_${local.tmdb_prefix}_discover_movie_${var.env}"
    glue_catalog_tb_discover_tv               = "tb_${local.tmdb_prefix}_discover_tv_${var.env}"
    glue_catalog_tb_now_playing_movie         = "tb_${local.tmdb_prefix}_now_playing_movie_${var.env}"
    glue_catalog_tb_genre_movie               = "tb_${local.tmdb_prefix}_genre_movie_${var.env}"
    glue_catalog_tb_genre_tv                  = "tb_${local.tmdb_prefix}_genre_tv_${var.env}"
    glue_catalog_tb_configuration_languages   = "tb_${local.tmdb_prefix}_configuration_languages_${var.env}"
    glue_catalog_tb_configuration_countries   = "tb_${local.tmdb_prefix}_configuration_countries_${var.env}"
    glue_catalog_tb_data_quality              = "tb_${local.tmdb_prefix}_data_quality_${var.env}"
    glue_catalog_tb_details_movie             = "tb_${local.tmdb_prefix}_details_movie_${var.env}"
    glue_catalog_tb_details_tv                = "tb_${local.tmdb_prefix}_details_tv_${var.env}"
    glue_catalog_tb_watch_providers_movie     = "tb_${local.tmdb_prefix}_watch_providers_movie_${var.env}"
    glue_catalog_tb_watch_providers_tv        = "tb_${local.tmdb_prefix}_watch_providers_tv_${var.env}"
    glue_catalog_tb_watch_providers_ref_movie = "tb_${local.tmdb_prefix}_watch_providers_ref_movie_${var.env}"
    glue_catalog_tb_watch_providers_ref_tv    = "tb_${local.tmdb_prefix}_watch_providers_ref_tv_${var.env}"
    glue_catalog_tb_discover_unified          = "tb_${local.tmdb_prefix}_discover_unified_${var.env}"

    # Lightsail
    lightsail_instance_name = "${local.tmdb_prefix}-${var.lightsail_instance_name}-${var.env}"
  }
}
