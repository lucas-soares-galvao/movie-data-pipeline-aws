# Variaveis especificas do ambiente de producao.
env = "prod"
s3_bucket_sor = "lsg-sa-east-1-bucket-sor-prod"
s3_bucket_aux = "lsg-sa-east-1-bucket-aux-prod"

glue_jobs = {
	etl = {
		app_folder    = "glue_etl"
		job_name      = "my-glue-etl-prod"
		iam_role_name = "glue-job-role-etl-prod"
		script_file   = "main.py"
		description   = "Glue ETL job (prod)"
	}
	data_quality = {
		app_folder    = "glue_data_quality"
		job_name      = "my-glue-data-quality-prod"
		iam_role_name = "glue-job-role-data-quality-prod"
		script_file   = "main.py"
		description   = "Glue Data Quality job (prod)"
	}
}
