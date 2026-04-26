from awsglue.utils import getResolvedOptions
import sys

from src.utils import process_tmdb, call_glue_data_quality

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

partitioned_tables = ["tb_movies_tmdb", "tb_tv_tmdb"]

for table in tables:
    if table in partitioned_tables:
        partition_columns = ["year", "month"]
        if table == "tb_movies_tmdb":
            date_column = "release_date"
        elif table == "tb_tv_tmdb":
            date_column = "first_air_date"
    else:
        partition_columns = None
        date_column = None

    process_tmdb(
        source_path=f"s3://{bucket_sor}/",
        destination_path=f"s3://{bucket_sot}/",
        database=database,
        table=table,
        partition_columns=partition_columns,
        date_column=date_column
    )

# Ensure partition_columns_str is 'year,month' if there is a partitioned table
partition_columns_str = ''
for table in tables:
    if table in partitioned_tables:
        partition_columns_str = 'year,month'
        break

glue = call_glue_data_quality(glue_data_quality_job_name, partition_columns=partition_columns_str)

if __name__ == "__main__":
    print("TMDB ETL executed successfully!")
    if glue:
        print(f"Data quality job started: {glue}")