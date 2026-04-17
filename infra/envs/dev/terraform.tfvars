# Variaveis especificas do ambiente de desenvolvimento.
env = "dev"
s3_bucket_sor = "lsg-sa-east-1-bucket-sor-dev"
s3_bucket_aux = "lsg-sa-east-1-bucket-aux-dev"

glue_jobs = {
	etl = {
		app_folder    = "glue_etl"
		job_name      = "my-glue-etl-dev"
		iam_role_name = "glue-job-role-etl-dev"
		script_file   = "main.py"
		description   = "Glue ETL job (dev)"
	}
	data_quality = {
		app_folder    = "glue_data_quality"
		job_name      = "my-glue-data-quality-dev"
		iam_role_name = "glue-job-role-data-quality-dev"
		script_file   = "main.py"
		description   = "Glue Data Quality job (dev)"
	}
}
