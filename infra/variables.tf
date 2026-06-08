# Raciocinio: declara contrato de entrada da infraestrutura para reutilizacao entre ambientes.

variable "env" {
  # Nome logico do ambiente, usado para nomes e isolamento de recursos.
  description = "Ambiente do serviço (ex.: dev, prod)"
  type        = string

  validation {
    condition     = contains(["dev", "prod"], lower(var.env))
    error_message = "A variavel env deve ser uma destas opcoes: dev ou prod."
  }
}

variable "finops_tag_value" {
  description = "Valor da tag FinOps aplicada aos recursos AWS compativeis para acompanhamento de custo"
  type        = string
  default     = "true"
}

############## IAM Roles and Policies ##############
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

############# ALARMS VARIABLES ##############
variable "glue_agg_notification_email" {
  description = "E-mail para receber notificacoes de execucao do Glue AGG"
  type        = string
  default     = "lsgalvao1000@gmail.com"
}
variable "glue_details_notification_email" {
  description = "E-mail para receber notificacoes de falha do Glue Details"
  type        = string
  default     = "lsgalvao1000@gmail.com"
}
variable "glue_data_quality_notification_email" {
  description = "E-mail para receber notificações de execução do Glue Data Quality"
  type        = string
  default     = "lsgalvao1000@gmail.com"
}
variable "glue_data_quality_metrics_notification_email" {
  description = "E-mail para receber notificações de avaliação de métricas do Glue Data Quality"
  type        = string
  default     = "lsgalvao1000@gmail.com"
}
variable "glue_etl_notification_email" {
  description = "E-mail para receber notificações de execução do Glue ETL"
  type        = string
  default     = "lsgalvao1000@gmail.com"
}
variable "lambda_notification_email" {
  description = "E-mail para receber notificações de execução da Lambda"
  type        = string
  default     = "lsgalvao1000@gmail.com"
}
variable "eventbridge_notification_email" {
  description = "E-mail para receber notificações de sucesso do EventBridge"
  type        = string
  default     = "lsgalvao1000@gmail.com"
}

############## S3 Buckets ##############
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

################ SECRETS MANAGER ############
variable "tmdb_secret_arn" {
  description = "ARN do segredo no Secrets Manager com a chave da TMDB"
  type        = string
}

############### LAMBDA ##############
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

############### GLUE ##############
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

variable "glue_agg_spec_table_name" {
  description = "Nome da tabela unificada gravada no bucket SPEC pelo Glue AGG"
  type        = string
  default     = "tb_discover_unified_tmdb"
}

variable "glue_catalog_database_movie_name" {
  description = "Nome do banco no Glue Catalog para tabelas de filmes TMDB"
  type        = string
  default     = "db_movie_tmdb"
}

variable "glue_catalog_database_tv_name" {
  description = "Nome do banco no Glue Catalog para tabelas de séries TMDB"
  type        = string
  default     = "db_tv_tmdb"
}

variable "glue_catalog_database_unified_name" {
  description = "Nome do banco no Glue Catalog para a tabela unificada e referências TMDB"
  type        = string
  default     = "db_unified_tmdb"
}

variable "glue_catalog_table_discover_movie_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de filmes da TMDB"
  type        = string
  default     = "tb_discover_movie_tmdb"
}

variable "glue_catalog_table_discover_tv_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de series da TMDB"
  type        = string
  default     = "tb_discover_tv_tmdb"
}

variable "glue_catalog_table_genre_movie_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de generos de filmes da TMDB"
  type        = string
  default     = "tb_genre_movie_tmdb"
}

variable "glue_catalog_table_genre_tv_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de generos de series da TMDB"
  type        = string
  default     = "tb_genre_tv_tmdb"
}

variable "glue_catalog_table_configuration_languages_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de linguas da TMDB"
  type        = string
  default     = "tb_configuration_languages_tmdb"

}

variable "glue_catalog_table_configuration_countries_name" {
  description = "Nome da tabela no Glue Catalog para a tabela de paises da TMDB"
  type        = string
  default     = "tb_configuration_countries_tmdb"
}

variable "glue_catalog_table_data_quality_name" {
  description = "Nome da tabela no Glue Catalog para resultados de Data Quality"
  type        = string
  default     = "tb_data_quality_tmdb"
}

variable "glue_catalog_table_details_movie_name" {
  description = "Nome da tabela no Glue Catalog para detalhes de filmes (runtime)"
  type        = string
  default     = "tb_details_movie_tmdb"
}

variable "glue_catalog_table_details_tv_name" {
  description = "Nome da tabela no Glue Catalog para detalhes de series (temporadas, episodios)"
  type        = string
  default     = "tb_details_tv_tmdb"
}

variable "glue_catalog_table_watch_providers_movie_name" {
  description = "Nome da tabela no Glue Catalog para watch providers BR de filmes"
  type        = string
  default     = "tb_watch_providers_movie_tmdb"
}

variable "glue_catalog_table_watch_providers_tv_name" {
  description = "Nome da tabela no Glue Catalog para watch providers BR de series"
  type        = string
  default     = "tb_watch_providers_tv_tmdb"
}

variable "glue_catalog_table_watch_providers_ref_movie_name" {
  description = "Nome da tabela no Glue Catalog para a lista de referência de provedores de filmes"
  type        = string
  default     = "tb_watch_providers_ref_movie_tmdb"
}

variable "glue_catalog_table_watch_providers_ref_tv_name" {
  description = "Nome da tabela no Glue Catalog para a lista de referência de provedores de series"
  type        = string
  default     = "tb_watch_providers_ref_tv_tmdb"
}

############# CLOUDWATCH LOGS ##############
variable "log_retention_days" {
  description = "Dias de retencao dos logs do CloudWatch. Use 1 para dev (economiza custo) e 30 para prod (permite investigar incidentes)"
  type        = number
  default     = 7
}
