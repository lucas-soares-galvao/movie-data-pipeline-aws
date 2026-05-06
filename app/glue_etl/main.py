from awsglue.utils import getResolvedOptions
import sys

from src.utils import process_tmdb, call_glue_data_quality

args = getResolvedOptions(sys.argv, [
    "S3_BUCKET_SOR",
    "S3_BUCKET_SOT",
    "MEDIA_TYPE",
    "DATABASE",
    "DISCOVER_TABLE",
    "GENRE_TABLE",
    "CONFIGURATION_TABLE",
    "CONFIGURATION",
    "PARTITION_COLUMNS",
    "GLUE_DATA_QUALITY_JOB_NAME"
])


bucket_sor = args["S3_BUCKET_SOR"]
bucket_sot = args["S3_BUCKET_SOT"]
database = args["DATABASE"]
discover_table = args["DISCOVER_TABLE"]
genre_table = args["GENRE_TABLE"]
configuration_table = args["CONFIGURATION_TABLE"]
configuration = args["CONFIGURATION"]
partition_columns = args.get("PARTITION_COLUMNS", "")
glue_data_quality_job_name = args["GLUE_DATA_QUALITY_JOB_NAME"]
media_type = args["MEDIA_TYPE"]

CONFIG = {
    "movie": [
        {"path": "discover", "table": discover_table, "date_column": "release_date"},
        {"path": "genre", "table": genre_table, "date_column": None},
        {"path": "configuration", "table": configuration_table, "date_column": None}
    ],
    "tv": [
        {"path": "discover", "table": discover_table, "date_column": "first_air_date"},
        {"path": "genre", "table": genre_table, "date_column": None},
        {"path": "configuration", "table": configuration_table, "date_column": None}
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

    if cfg["path"] == "configuration":
        s3_source_path = f"s3://{bucket_sor}/tmdb/{cfg['path']}/{configuration}/"
    else:
        s3_source_path = f"s3://{bucket_sor}/tmdb/{cfg['path']}/{media_type}/"

    result = process_tmdb(
        source_path=s3_source_path,
        destination_path=f"s3://{bucket_sot}/tmdb/{cfg['table']}/",
        database=database,
        table=table,
        partition_columns=partition_columns_list,
        date_column=date_column
    )

    partitions = result.get("partitions", [])

    print(partitions)

    if partition_columns_list:
        call_glue_data_quality(
            glue_data_quality_job_name,
            database=database,
            table=table,
            partition_columns=",".join(partition_columns_list),
            partition_values=partitions
        )
    else:
        call_glue_data_quality(
            glue_data_quality_job_name,
            database=database,
            table=table,
            partition_columns="",
            partition_values=None
        )


if __name__ == "__main__":
    print("TMDB ETL executed successfully!")