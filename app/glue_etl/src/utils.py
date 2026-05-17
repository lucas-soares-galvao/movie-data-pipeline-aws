import awswrangler as wr
import boto3
import pandas as pd


REQUIRED_ARGS = [
    "S3_BUCKET_SOR",
    "S3_BUCKET_SOT",
    "MEDIA_TYPE",
    "DATABASE",
    "DISCOVER_TABLE",
    "GENRE_TABLE",
    "CONFIGURATION_TABLE",
    "CONFIGURATION",
    "PARTITION_COLUMNS",
    "GLUE_DATA_QUALITY_JOB_NAME",
    "YEAR"
]

TABLES_BY_MEDIA = {
    "movie": [
        {"path": "discover", "table_arg": "DISCOVER_TABLE", "date_column": "release_date"},
        {"path": "genre", "table_arg": "GENRE_TABLE", "date_column": None},
        {"path": "configuration", "table_arg": "CONFIGURATION_TABLE", "date_column": None}
    ],
    "tv": [
        {"path": "discover", "table_arg": "DISCOVER_TABLE", "date_column": "first_air_date"},
        {"path": "genre", "table_arg": "GENRE_TABLE", "date_column": None},
        {"path": "configuration", "table_arg": "CONFIGURATION_TABLE", "date_column": None}
    ]
}

TABLE_SCOPE_ALL = "all"
TABLE_SCOPE_DISCOVER = "discover"
TABLE_SCOPE_STATIC = "static"


def _add_temporal_partition_columns(df, date_column):
    df[date_column] = pd.to_datetime(df[date_column], errors="coerce")
    df["year"] = df[date_column].dt.year.astype("Int64").astype(str)
    df["month"] = df[date_column].dt.strftime("%m")
    return df


def _build_partition_values(df, partition_columns):
    if not partition_columns:
        return []

    partition_values = []
    unique_partitions = df[partition_columns].drop_duplicates()
    for _, row in unique_partitions.iterrows():
        part_str = "/".join(f"{col}={row[col]}" for col in partition_columns)
        partition_values.append(part_str)
    return partition_values


def _is_temporal_partition(partition_columns, date_column):
    return bool(date_column) and bool(partition_columns)


def process_tmdb(
    source_path,
    destination_path,
    database,
    table,
    partition_columns=None,
    date_column=None
):
    """Read TMDB JSON from S3, transform when needed, and write Parquet to S3."""
    df = wr.s3.read_json(source_path)
    mode = "overwrite_partitions" if partition_columns else "overwrite"

    if _is_temporal_partition(partition_columns, date_column):
        df = _add_temporal_partition_columns(df, date_column)

    wr.s3.to_parquet(
        df=df,
        path=destination_path,
        dataset=True,
        partition_cols=partition_columns if partition_columns else [],
        database=database,
        table=table,
        mode=mode
    )

    partition_values = _build_partition_values(df, partition_columns)

    return {
        "partitions": partition_values
    }

def call_glue_data_quality(job_name, database, table, partition_values=None):
    """Trigger the Glue Data Quality job for a given catalog table."""
    glue = boto3.client("glue")

    arguments = {
        "--DATABASE": database,
        "--TABLE": table
    }
    if partition_values:
        arguments["--PARTITION_VALUES"] = ",".join(partition_values)

    response = glue.start_job_run(
        JobName=job_name,
        Arguments=arguments
    )

    return {
        "job_name": job_name,
        "job_run_id": response["JobRunId"]
    }


def build_tables_config(media_type, args):
    """Build per-table ETL config according to media type."""
    configs = TABLES_BY_MEDIA.get(media_type)
    if configs is None:
        raise ValueError(f"Unsupported MEDIA_TYPE: {media_type}")

    return [
        {
            "path": cfg["path"],
            "table": args[cfg["table_arg"]],
            "date_column": cfg["date_column"]
        }
        for cfg in configs
    ]


def build_source_path(bucket_sor, table_path, media_type, configuration, year=None):
    """Build S3 source path for table extraction."""
    if table_path == "configuration":
        return f"s3://{bucket_sor}/tmdb/{table_path}/{configuration}/"
    if table_path == "discover" and year:
        return f"s3://{bucket_sor}/tmdb/{table_path}/{media_type}/year={year}/"
    return f"s3://{bucket_sor}/tmdb/{table_path}/{media_type}/"


def build_partition_columns(partition_columns, date_column):
    """Return partition columns only for temporal discover datasets."""
    if not partition_columns or not date_column:
        return []
    return [column.strip() for column in partition_columns.split(",") if column.strip()]


def filter_tables_config(configs, table_scope):
    """Filter ETL tables by requested execution scope."""
    if table_scope == TABLE_SCOPE_DISCOVER:
        return [cfg for cfg in configs if cfg["path"] == "discover"]
    if table_scope == TABLE_SCOPE_STATIC:
        return [cfg for cfg in configs if cfg["path"] != "discover"]
    return configs


def resolve_dq_partition_values(table_path, partition_columns_list, year):
    """Determine which partition values to send to the Data Quality job."""
    if not partition_columns_list:
        return None
    if year and table_path == "discover":
        return [f"year={year}"]
    return None


def run_etl(args):
    """Run ETL for all configured TMDB tables and trigger Data Quality."""
    bucket_sor = args["S3_BUCKET_SOR"]
    bucket_sot = args["S3_BUCKET_SOT"]
    media_type = args["MEDIA_TYPE"]
    database = args["DATABASE"]
    configuration = args["CONFIGURATION"]
    partition_columns = args.get("PARTITION_COLUMNS", "")
    glue_data_quality_job_name = args["GLUE_DATA_QUALITY_JOB_NAME"]
    year = args.get("YEAR")
    table_scope = args.get("TABLE_SCOPE", TABLE_SCOPE_ALL)

    table_configs = filter_tables_config(build_tables_config(media_type, args), table_scope)

    for cfg in table_configs:
        table = cfg["table"]
        date_column = cfg["date_column"]
        partition_columns_list = build_partition_columns(partition_columns, date_column)
        source_year = year if table_scope == TABLE_SCOPE_DISCOVER and cfg["path"] == "discover" else None

        result = process_tmdb(
            source_path=build_source_path(bucket_sor, cfg["path"], media_type, configuration, year=source_year),
            destination_path=f"s3://{bucket_sot}/tmdb/{table}/",
            database=database,
            table=table,
            partition_columns=partition_columns_list,
            date_column=date_column
        )

        partitions = result.get("partitions", [])
        print(f"Processed table={table}, partitions={partitions}")

        dq_partition_values = resolve_dq_partition_values(
            table_path=cfg["path"],
            partition_columns_list=partition_columns_list,
            year=year
        )
        call_glue_data_quality(
            glue_data_quality_job_name,
            database=database,
            table=table,
            partition_values=dq_partition_values
        )