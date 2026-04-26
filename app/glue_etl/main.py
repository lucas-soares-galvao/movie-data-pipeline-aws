from awsglue.utils import getResolvedOptions
import sys

from src.utils import process_tmdb, call_glue_data_quality

args = getResolvedOptions(sys.argv, [
    "S3_BUCKET_SOR",
    "S3_BUCKET_SOT",
    "GLUE_CATALOG_DATABASE",
    "GLUE_DATA_QUALITY_JOB_NAME",
    "MWEDIA_TYPE"
])


bucket_sor = args["S3_BUCKET_SOR"]
bucket_sot = args["S3_BUCKET_SOT"]
database = args["GLUE_CATALOG_DATABASE"]
glue_data_quality_job_name = args["GLUE_DATA_QUALITY_JOB_NAME"]
media_type = args["MEDIA_TYPE"]

CONFIG = {
    "movie": [
        {"table": "tb_movies_tmdb", "date_column": "release_date"},
        {"table": "tb_genre_movie_tmdb", "date_column": None}
    ],
    "tv": [
        {"table": "tb_tv_tmdb", "date_column": "first_air_date"},
        {"table": "tb_genre_tv_tmdb", "date_column": None}
    ]
}

tables_config = CONFIG.get(media_type, [])

for cfg in tables_config:
    table = cfg["table"]
    date_column = cfg["date_column"]

    partition_columns = ["year", "month"] if date_column else None

    process_tmdb(
        source_path=f"s3://{bucket_sor}/",
        destination_path=f"s3://{bucket_sot}/",
        database=database,
        table=table,
        partition_columns=partition_columns,
        date_column=date_column
    )

    call_glue_data_quality(
        glue_data_quality_job_name,
        partition_columns="year,month" if partition_columns else ""
    )


if __name__ == "__main__":
    print("TMDB ETL executed successfully!")