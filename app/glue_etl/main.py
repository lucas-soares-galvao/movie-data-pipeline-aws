from awsglue.utils import getResolvedOptions
import sys

from src.utils import processar_tmdb, chamar_glue_data_quality

args = getResolvedOptions(sys.argv, [
    "GLUE_CATALOG_DATABASE",
    "GLUE_CATALOG_TABLES",
    "S3_BUCKET_SOR",
    "S3_BUCKET_SOT",
    "GLUE_DATA_QUALITY_JOB_NAME"
])

database = args["GLUE_CATALOG_DATABASE"]
tables = args["GLUE_CATALOG_TABLES"].split(",")
bucket_sor = args["S3_BUCKET_SOR"]
bucket_sot = args["S3_BUCKET_SOT"]
glue_data_quality_job_name = args["GLUE_DATA_QUALITY_JOB_NAME"]

tabelas_com_particao = ["tb_movies_tmdb", "tb_tv_tmdb"]

for table in tables:

    processar_tmdb(
        input_path=f"s3://{bucket_sor}/",
        output_path=f"s3://{bucket_sot}/",
        database=database,
        table=table,
        partition_cols=["year", "month"] if table in tabelas_com_particao else None
    )

if processar_tmdb:
    glue = chamar_glue_data_quality(glue_data_quality_job_name)
else:    
    glue = None

if __name__ == "__main__":
    print("ETL de TMDB executado com sucesso!")
    if glue:
        print(f"Job de qualidade de dados iniciado: {glue}")