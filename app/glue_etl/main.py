from awsglue.utils import getResolvedOptions
import sys

from src.utils import process_tmdb, call_glue_data_quality

args = getResolvedOptions(sys.argv, [
    "S3_BUCKET_SOR",
    "S3_BUCKET_SOT",
    "MEDIA_TYPE",
    "DATABASE",
    "TABLE",
    "GENRE_TABLE",
    "PARTITION_COLUMNS",
    "GLUE_DATA_QUALITY_JOB_NAME"
])


bucket_sor = args["S3_BUCKET_SOR"]
bucket_sot = args["S3_BUCKET_SOT"]
database = args["DATABASE"]
table_tmdb = args["TABLE"]
table_genre = args["GENRE_TABLE"]
partition_columns = args.get("PARTITION_COLUMNS", "")
glue_data_quality_job_name = args["GLUE_DATA_QUALITY_JOB_NAME"]
media_type = args["MEDIA_TYPE"]

CONFIG = {
    "movie": [
        {"table": table_tmdb, "date_column": "release_date"},
        {"table": table_genre, "date_column": None}
    ],
    "tv": [
        {"table": table_tmdb, "date_column": "first_air_date"},
        {"table": table_genre, "date_column": None}
    ]
}

tables_config = CONFIG.get(media_type, [])

for cfg in tables_config:
    table = cfg["table"]
    date_column = cfg["date_column"]

    partition_columns_list = (
        partition_columns.split(",")
        if partition_columns and date_column
        else []
    )

    process_tmdb(
        source_path=f"s3://{bucket_sor}/{table}/",
        destination_path=f"s3://{bucket_sot}/{table}/",
        database=database,
        table=table,
        partition_columns=partition_columns_list,
        date_column=date_column
    )

    call_glue_data_quality(
        glue_data_quality_job_name,
        partition_columns=",".join(partition_columns_list)
    )


if __name__ == "__main__":
    print("TMDB ETL executed successfully!")