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

    if table in tabelas_com_particao:

        partitions_cols = ["year", "month"]

        if table == "tb_movies_tmdb":
            partiton_date_col = "release_date"
        elif table == "tb_tv_tmdb":
            partiton_date_col = "first_air_date"
    
    else:
        partitions_cols = None
        partiton_date_col = None

    processar_tmdb(
        input_path=f"s3://{bucket_sor}/",
        output_path=f"s3://{bucket_sot}/",
        database=database,
        table=table,
        partitions_cols=partitions_cols,
        partition_date_col=partiton_date_col
    )



# Garante que partitions_cols_str seja 'year,month' se houver tabela particionada
partitions_cols_str = ''
for table in tables:
    if table in tabelas_com_particao:
        partitions_cols_str = 'year,month'
        break

glue = chamar_glue_data_quality(glue_data_quality_job_name, partition_cols=partitions_cols_str)

if __name__ == "__main__":
    print("ETL de TMDB executado com sucesso!")
    if glue:
        print(f"Job de qualidade de dados iniciado: {glue}")