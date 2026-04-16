# Variaveis centralizadas para facilitar reuso entre ambientes (dev/prod).
variable "s3_bucket_aux" {
  description = "The name of the auxiliary S3 bucket for Glue scripts"
  type        = string
  default     = "lsg-sa-east-1-bucket-aux"
}

variable "s3_bucket_sot" {
  description = "The name of the source S3 bucket for Glue scripts"
  type        = string
  default     = "lsg-sa-east-1-bucket-sot"
}

variable "env" {
  # Nome logico do ambiente, usado em naming e isolamento de recursos.
  description = "The environment for the Glue job (e.g., dev, prod)"
  type        = string
}

variable "glue_job_name" {
  description = "The name of the Glue job to create"
  type        = string
  default     = "my-glue-etl-job"
}

variable "iam_role_name" {
  description = "The name of the IAM role for Glue jobs"
  type        = string
  default     = "glue-job-role"
}
