variable "bucket_name" {
  description = "The name of the S3 bucket to create"
  type        = string
  default     = "my-terraform-bucket"
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