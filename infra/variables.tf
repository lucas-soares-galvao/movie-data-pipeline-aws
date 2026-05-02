############# GENERAL VARIABLES ##############
variable "env" {
  # Logical name of the environment, used for naming and resource isolation.
  description = "The environment for the Glue job (e.g., dev, prod)"
  type        = string
}

variable "account_id" {
  description = "AWS account ID"
  type        = string
}

############## IAM Roles and Policies ##############
variable "iam_role_glue" {
  description = "IAM role name for Glue jobs"
  type        = string
  default     = "glue-job-role-etl"
}

variable "iam_role_lambda" {
  description = "IAM role name for Lambda function"
  type        = string
  default     = "lambda-role"
}

############# ALARMS VARIABLES ##############
variable "glue_data_quality_notification_email" {
  description = "E-mail para receber notificações de execução do Glue Data Quality"
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
  description = "Temporary bucket name for Athena scripts"
  type        = string
  default     = "lsg-sa-east-1-bucket-temp"
}

variable "s3_bucket_sor" {
  description = "Main bucket name for input/output data processed by Lambda"
  type        = string
  default     = "lsg-sa-east-1-bucket-sor"
}

variable "s3_bucket_sot" {
  description = "Main bucket name for input/output data processed by Glue ETL"
  type        = string
  default     = "lsg-sa-east-1-bucket-sot"
}

variable "s3_bucket_spec" {
  description = "Main bucket name for input/output data processed by Glue ETL"
  type        = string
  default     = "lsg-sa-east-1-bucket-spec"
}

variable "s3_bucket_data_quality" {
  description = "Main bucket name for input/output data processed by Glue Data Quality"
  type        = string
  default     = "lsg-sa-east-1-bucket-data-quality"
}

################ SECRETS MANAGER ############
variable "tmdb_secret_arn" {
  description = "ARN of the secret in Secrets Manager with the TMDB key"
  type        = string
}

############### LAMBDA ##############
variable "lambda_api_path_app" {
  description = "Path to the Python modules of the application for Lambda API"
  type        = string
  default     = "lambda_api"
}

variable "lambda_api_name" {
  description = "Name of the Lambda function to be created per environment"
  type        = string
  default     = "lambda-api"
}

############### GLUE ##############
variable "glue_etl_path_app" {
  description = "Path to the Python modules of the application for Glue ETL"
  type        = string
  default     = "glue_etl"
}

variable "glue_etl_job_name" {
  description = "Name of the Glue ETL job to be created per environment"
  type        = string
  default     = "glue-etl"
}

variable "glue_data_quality_path_app" {
  description = "Path to the Python modules of the application for Glue Data Quality"
  type        = string
  default     = "glue_data_quality"
}

variable "glue_data_quality_job_name" {
  description = "Name of the Glue Data Quality job to be created per environment"
  type        = string
  default     = "glue-data-quality"
}

variable "glue_catalog_database_name" {
  description = "Name of the database in Glue Catalog for the TMDB movie table"
  type        = string
  default     = "db_tmdb"
}

variable "glue_catalog_table_discover_movie_name" {
  description = "Name of the table in Glue Catalog for the TMDB movie table"
  type        = string
  default     = "tb_discover_movie_tmdb"
}

variable "glue_catalog_table_discover_tv_name" {
  description = "Name of the table in Glue Catalog for the TMDB TV shows table"
  type        = string
  default     = "tb_discover_tv_tmdb"
}

variable "glue_catalog_table_genre_movie_name" {
  description = "Name of the table in Glue Catalog for the TMDB movie genres table"
  type        = string
  default     = "tb_genre_movie_tmdb"
}

variable "glue_catalog_table_genre_tv_name" {
  description = "Name of the table in Glue Catalog for the TMDB TV genres table"
  type        = string
  default     = "tb_genre_tv_tmdb"
}

variable "glue_catalog_table_configuration_languages_name" {
  description = "Name of the table in Glue Catalog for the TMDB languages table"
  type        = string
  default     = "tb_configuration_languages_tmdb"
  
}

variable "glue_catalog_table_configuration_countries_name" {
  description = "Name of the table in Glue Catalog for the TMDB countries table"
  type        = string
  default     = "tb_configuration_countries_tmdb"
}