# Variaveis centralizadas para facilitar reuso entre ambientes (dev/prod).
variable "s3_bucket_aux" {
  description = "The name of the auxiliary S3 bucket for Glue scripts"
  type        = string
  default     = "lsg-sa-east-1-bucket-aux"
}

variable "s3_bucket_sor" {
  description = "The name of the source S3 bucket for Glue scripts"
  type        = string
  default     = "lsg-sa-east-1-bucket-sor"
}

variable "s3_bucket_sot" {
  description = "The name of the source S3 bucket for Glue scripts"
  type        = string
  default     = "lsg-sa-east-1-bucket-sot"
}

variable "s3_bucket_spec" {
  description = "The name of the source S3 bucket for Glue scripts"
  type        = string
  default     = "lsg-sa-east-1-bucket-spec"
}

variable "env" {
  # Nome logico do ambiente, usado em naming e isolamento de recursos.
  description = "The environment for the Glue job (e.g., dev, prod)"
  type        = string
}

variable "lambda_api_aux" {
  description = "The service Lambda functions"
  type        = string
  default     = "lambda_api"
}

variable "lambda_api_name" {
  description = "The name of the Lambda function"
  type        = string
  default     = "my-lambda-api-function"
}

variable "glue_etl_aux" {
  description = "The service Glue ETL"
  type        = string
  default     = "glue_etl"
}

variable "glue_etl_job_name" {
  description = "The name of the Glue ETL job to create"
  type        = string
  default     = "my-glue-etl-job"
}

variable "glue_data_quality_aux" {
  description = "The service Glue Data Quality"
  type        = string
  default     = "glue_data_quality"
}

variable "glue_data_quality_job_name" {
  description = "The name of the Glue Data Quality job to create"
  type        = string
  default     = "my-glue-data-quality-job"
}

variable "iam_role_name" {
  description = "The name of the IAM role for Glue jobs"
  type        = string
  default     = "glue-job-role"
}
