# =============================================================================
# variables.tf — Variáveis de entrada; valores por ambiente em envs/*/terraform.tfvars
# =============================================================================

# =============================================================================
# AMBIENTE
# =============================================================================

variable "env" {
  description = "Ambiente do serviço (ex.: dev, prod)"
  type        = string

  # Validação: garante que só "dev" ou "prod" sejam aceitos.
  # Se alguém passar "staging" ou "test", o Terraform falha com mensagem clara.
  validation {
    condition     = contains(["dev", "prod"], lower(var.env))
    error_message = "A variavel env deve ser uma destas opcoes: dev ou prod."
  }
}

variable "finops_tag_value" {
  description = "Nome do projeto/centro de custo para a tag FinOps (usada no Cost Explorer da AWS)"
  type        = string
  default     = "proj-filmes-aws"
}

# =============================================================================
# IAM — ROLES E POLÍTICAS
# =============================================================================

variable "iam_role_glue" {
  description = "Nome da role IAM para jobs Glue"
  type        = string
  default     = "glue-job-role-etl"
}

variable "iam_role_lambda" {
  description = "Nome da role IAM para a funcao Lambda"
  type        = string
  default     = "lambda-role"
}

# =============================================================================
# ALARMES — NOTIFICAÇÕES POR EMAIL
# =============================================================================

variable "glue_agg_notification_email" {
  description = "E-mail para receber notificacoes de execucao do Glue AGG"
  type        = string
}

variable "glue_details_notification_email" {
  description = "E-mail para receber notificacoes de falha do Glue Details"
  type        = string
}

variable "glue_data_quality_notification_email" {
  description = "E-mail para receber notificações de execução do Glue Data Quality"
  type        = string
}

variable "glue_data_quality_metrics_notification_email" {
  description = "E-mail para receber notificações de avaliação de métricas do Glue Data Quality"
  type        = string
}

variable "glue_etl_notification_email" {
  description = "E-mail para receber notificações de execução do Glue ETL"
  type        = string
}

variable "lambda_notification_email" {
  description = "E-mail para receber notificações de execução da Lambda"
  type        = string
}

variable "eventbridge_notification_email" {
  description = "E-mail para receber notificações de falha do EventBridge"
  type        = string
}

variable "sfn_backfill_notification_email" {
  description = "E-mail para receber notificacoes de falha do Step Functions Backfill"
  type        = string
}

# =============================================================================
# BUCKETS S3 — ARQUITETURA MEDALHÃO
# =============================================================================
# Os nomes têm sufixo "-dev" ou "-prod" adicionado pelo locals.tf.

variable "s3_bucket_aux" {
  description = "Auxiliary bucket name for Python code"
  type        = string
  default     = "lsg-sa-east-1-bucket-aux"
}

variable "s3_bucket_temp" {
  description = "Nome do bucket temporario para scripts do Athena"
  type        = string
  default     = "lsg-sa-east-1-bucket-temp"
}

variable "s3_bucket_sor" {
  description = "Nome do bucket principal para dados de entrada/saida processados pela Lambda"
  type        = string
  default     = "lsg-sa-east-1-bucket-sor"
}

variable "s3_bucket_sot" {
  description = "Nome do bucket principal para dados de entrada/saida processados pelo Glue ETL"
  type        = string
  default     = "lsg-sa-east-1-bucket-sot"
}

variable "s3_bucket_spec" {
  description = "Nome do bucket SPEC para dados agregados e especializados gerados pelo Glue AGG"
  type        = string
  default     = "lsg-sa-east-1-bucket-spec"
}

variable "s3_bucket_data_quality" {
  description = "Nome do bucket principal para dados de entrada/saida processados pelo Glue Data Quality"
  type        = string
  default     = "lsg-sa-east-1-bucket-data-quality"
}

# =============================================================================
# SECRETS MANAGER
# =============================================================================

variable "tmdb_secret_arn" {
  description = "ARN do segredo no Secrets Manager com a chave da TMDB"
  type        = string
  # Sem "default" pois é um valor sensível que deve ser passado via .tfvars ou CI/CD
}

# =============================================================================
# LAMBDA API
# =============================================================================

variable "lambda_api_path_app" {
  description = "Caminho para os modulos Python da aplicacao da Lambda API"
  type        = string
  default     = "lambda_api"
}

variable "lambda_api_name" {
  description = "Nome da funcao Lambda a ser criada por ambiente"
  type        = string
  default     = "lambda-api"
}

# =============================================================================
# GLUE ETL — Processamento Básico de Dados
# =============================================================================

variable "glue_etl_path_app" {
  description = "Caminho para os modulos Python da aplicacao do Glue ETL"
  type        = string
  default     = "glue_etl"
}

variable "glue_etl_job_name" {
  description = "Nome do job Glue ETL a ser criado por ambiente"
  type        = string
  default     = "glue-etl"
}

# =============================================================================
# GLUE DATA QUALITY — Validação de Qualidade dos Dados
# =============================================================================

variable "glue_data_quality_path_app" {
  description = "Caminho para os modulos Python da aplicacao do Glue Data Quality"
  type        = string
  default     = "glue_data_quality"
}

variable "glue_data_quality_job_name" {
  description = "Nome do job Glue Data Quality a ser criado por ambiente"
  type        = string
  default     = "glue-data-quality"
}

# =============================================================================
# GLUE AGG — Agregação e Unificação Final
# =============================================================================

variable "glue_agg_path_app" {
  description = "Caminho para os modulos Python da aplicacao do Glue AGG"
  type        = string
  default     = "glue_agg"
}

variable "glue_agg_job_name" {
  description = "Nome do job Glue AGG a ser criado por ambiente"
  type        = string
  default     = "glue-agg"
}

# =============================================================================
# GLUE DETAILS — Enriquecimento com Detalhes por Título
# =============================================================================

variable "glue_details_path_app" {
  description = "Caminho para os modulos Python da aplicacao do Glue Details"
  type        = string
  default     = "glue_details"
}

variable "glue_details_job_name" {
  description = "Nome do job Glue Details a ser criado por ambiente"
  type        = string
  default     = "glue-details"
}

# =============================================================================
# GLUE CATALOG — Registro de Tabelas
# =============================================================================

variable "glue_agg_spec_tb_name" {
  description = "Nome da tabela unificada gravada no bucket SPEC pelo Glue AGG"
  type        = string
  default     = "tb_discover_unified"
}

variable "glue_catalog_db_movie_name" {
  description = "Nome do banco no Glue Catalog para tabelas de filmes TMDB"
  type        = string
  default     = "db_movie"
}

variable "glue_catalog_db_tv_name" {
  description = "Nome do banco no Glue Catalog para tabelas de séries TMDB"
  type        = string
  default     = "db_tv"
}

variable "glue_catalog_db_unified_name" {
  description = "Nome do banco no Glue Catalog para a tabela unificada e referências TMDB"
  type        = string
  default     = "db_unified"
}

variable "glue_catalog_tb_discover_movie_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de filmes da TMDB"
  type        = string
  default     = "tb_discover_movie"
}

variable "glue_catalog_tb_now_playing_movie_name" {
  description = "Nome da tabela no Glue Catalog para filmes atualmente em cartaz nos cinemas"
  type        = string
  default     = "tb_now_playing_movie"
}

variable "glue_catalog_tb_discover_tv_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de series da TMDB"
  type        = string
  default     = "tb_discover_tv"
}

variable "glue_catalog_tb_genre_movie_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de generos de filmes da TMDB"
  type        = string
  default     = "tb_genre_movie"
}

variable "glue_catalog_tb_genre_tv_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de generos de series da TMDB"
  type        = string
  default     = "tb_genre_tv"
}

variable "glue_catalog_tb_configuration_languages_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de linguas da TMDB"
  type        = string
  default     = "tb_configuration_languages"
}

variable "glue_catalog_tb_configuration_countries_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de paises da TMDB"
  type        = string
  default     = "tb_configuration_countries"
}

variable "glue_catalog_tb_data_quality_name" {
  description = "Nome da tabela no Glue Catalog para resultados de Data Quality"
  type        = string
  default     = "tb_data_quality"
}

variable "glue_catalog_tb_details_movie_name" {
  description = "Nome da tabela no Glue Catalog para detalhes de filmes (runtime)"
  type        = string
  default     = "tb_details_movie"
}

variable "glue_catalog_tb_details_tv_name" {
  description = "Nome da tabela no Glue Catalog para detalhes de series (temporadas, episodios)"
  type        = string
  default     = "tb_details_tv"
}

variable "glue_catalog_tb_watch_providers_movie_name" {
  description = "Nome da tabela no Glue Catalog para watch providers BR de filmes"
  type        = string
  default     = "tb_watch_providers_movie"
}

variable "glue_catalog_tb_watch_providers_tv_name" {
  description = "Nome da tabela no Glue Catalog para watch providers BR de series"
  type        = string
  default     = "tb_watch_providers_tv"
}

variable "glue_catalog_tb_watch_providers_ref_movie_name" {
  description = "Nome da tabela no Glue Catalog para a lista de referência de provedores de filmes"
  type        = string
  default     = "tb_watch_providers_ref_movie"
}

variable "glue_catalog_tb_watch_providers_ref_tv_name" {
  description = "Nome da tabela no Glue Catalog para a lista de referência de provedores de series"
  type        = string
  default     = "tb_watch_providers_ref_tv"
}

# =============================================================================
# LIGHTSAIL — Servidor do App FilmBot
# =============================================================================

variable "lightsail_enabled" {
  description = "Habilita a instância Lightsail. false = instância destruída (reduz custo em dev)."
  type        = bool
  default     = true
}

variable "lightsail_instance_name" {
  description = "Nome da instância Lightsail para o agente IA (FilmBot)"
  type        = string
  default     = "filmbot"
}

variable "lightsail_ssh_allowed_cidrs" {
  description = "CIDRs permitidos na porta 22 do Lightsail. Sem default para forçar definição explícita por ambiente."
  type        = list(string)
}

# =============================================================================
# CI/CD — Role do GitHub Actions e backend do Terraform
# =============================================================================

variable "cicd_role_name" {
  description = "Prefixo da role IAM do GitHub Actions (sufixo -{env} adicionado automaticamente)"
  type        = string
  default     = "lsg-github-actions"
}

variable "cicd_statefile_s3_bucket" {
  description = "Nome do bucket S3 usado como backend do Terraform (state file)"
  type        = string
}

variable "cicd_lock_dynamodb_table" {
  description = "Nome da tabela DynamoDB usada para lock do Terraform state"
  type        = string
}

# =============================================================================
# CLOUDWATCH LOGS — Retenção de Logs
# =============================================================================

variable "log_retention_days" {
  description = "Dias de retencao dos logs do CloudWatch. Use 1 para dev (economiza custo) e 5 para prod (permite investigar incidentes)"
  type        = number
  default     = 7
}
