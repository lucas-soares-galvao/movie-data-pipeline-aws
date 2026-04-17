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

variable "env" {
  # Nome logico do ambiente, usado em naming e isolamento de recursos.
  description = "The environment for the Glue job (e.g., dev, prod)"
  type        = string
}

variable "lambda" {
  description = "The service Lambda functions"
  type        = string
  default     = "lambda"
}

variable "glue_jobs" {
  description = "Glue jobs to provision (etl, data_quality, etc.)"
  type = map(object({
    app_folder    = string
    job_name      = string
    iam_role_name = string
    script_file   = optional(string, "main.py")
    description   = optional(string, "")
  }))

  default = {
    etl = {
      app_folder    = "glue_etl"
      job_name      = "my-glue-etl-job"
      iam_role_name = "glue-job-role-etl"
      script_file   = "main.py"
      description   = "Glue ETL job"
    }
    data_quality = {
      app_folder    = "glue_data_quality"
      job_name      = "my-glue-data-quality-job"
      iam_role_name = "glue-job-role-data-quality"
      script_file   = "main.py"
      description   = "Glue Data Quality job"
    }
  }
}
