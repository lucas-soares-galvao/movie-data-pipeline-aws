# Variaveis especificas do ambiente de desenvolvimento.
env = "dev"

iam_role_glue = "glue-job-role-etl-dev"
iam_role_lambda = "lambda-role-dev"

s3_bucket_aux = "lsg-sa-east-1-bucket-aux-dev"
s3_bucket_temp = "lsg-sa-east-1-bucket-temp-dev"
s3_bucket_sor = "lsg-sa-east-1-bucket-sor-dev"
s3_bucket_sot = "lsg-sa-east-1-bucket-sot-dev"
s3_bucket_spec = "lsg-sa-east-1-bucket-spec-dev"

tmdb_secret_arn = "arn:aws:secretsmanager:sa-east-1:298984097610:secret:tmdb_api_key_dev-BSZF4M"

lambda_api_name = "lambda-api-dev"

glue_etl_job_name = "glue-etl-dev"
glue_data_quality_job_name = "glue-data-quality-dev"

eventbridge_notification_email        = "lsgalvao1000@gmail.com"
lambda_notification_email             = "lsgalvao1000@gmail.com"
glue_etl_notification_email           = "lsgalvao1000@gmail.com"
glue_data_quality_notification_email  = "lsgalvao1000@gmail.com"
