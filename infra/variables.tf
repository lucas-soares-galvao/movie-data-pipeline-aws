############# VARIÁVEIS GERAIS ##############
variable "env" {
  # Nome logico do ambiente, usado em naming e isolamento de recursos.
  description = "The environment for the Glue job (e.g., dev, prod)"
  type        = string
}

############## IAM Roles e Policies ##############
variable "iam_role_glue" {
  description = "Nome do IAM role para os jobs do Glue"
  type        = string
}

variable "iam_role_lambda" {
  description = "Nome do IAM role para a funcao Lambda"
  type        = string
}

############## S3 Buckets ##############
variable "s3_bucket_aux" {
  description = "Nome do bucket auxiliar para códigos em python"
  type        = string
}

variable "s3_bucket_temp" {
  description = "Nome do bucket temporário para scripts do Athena"
  type        = string
}

variable "s3_bucket_sor" {
  description = "Nome do bucket principal para dados de entrada/saida processados pela Lambda"
  type        = string
}

variable "s3_bucket_sot" {
  description = "Nome do bucket principal para dados de entrada/saida processados pelo Glue ETL"
  type        = string
}

variable "s3_bucket_spec" {
  description = "Nome do bucket principal para dados de entrada/saida processados pela Glue ETL"
  type        = string
}

################ SECRETS MANAGER ############
variable "tmdb_secret_arn" {
  description = "ARN do secret no Secrets Manager com a chave da TMDB"
  type        = string
}

############### LAMBDA ##############

variable "lambda_api_path_app" {
  description = "Caminho dos modulos Python da aplicacao para o Lambda API"
  type        = string
  default     = "lambda_api"
}

variable "lambda_api_name" {
  description = "Nome da funcao Lambda a ser criada por ambiente"
  type        = string
}

############### GLUE ##############

variable "glue_etl_path_app" {
  description = "Caminho dos modulos Python da aplicacao para o Glue ETL"
  type        = string
  default     = "glue_etl"
}

variable "glue_etl_job_name" {
  description = "Nome do Glue ETL job a ser criado por ambiente"
  type        = string
}

variable "glue_data_quality_path_app" {
  description = "Caminho dos modulos Python da aplicacao para o Glue Data Quality"
  type        = string
  default     = "glue_data_quality"
}

variable "glue_data_quality_job_name" {
  description = "Nome do Glue Data Quality job a ser criado por ambiente"
  type        = string
}

variable "glue_catalog_database_name" {
  description = "Nome do database no Glue Catalog para a tabela de filmes TMDB"
  type        = string
  default     = "db_movies_tmdb"
}

variable "glue_catalog_table_list_name" {
  description = "Lista de nomes de tabelas do Glue Catalog, separadas por vírgula"
  type        = string
  default     = "tb_movies_tmdb,tb_tv_tmdb,tb_genre_movie_tmdb,tb_genre_tv_tmdb"
}