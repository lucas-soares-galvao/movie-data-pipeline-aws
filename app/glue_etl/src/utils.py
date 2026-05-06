import awswrangler as wr
import boto3
import pandas as pd


def process_tmdb(
    source_path,
    destination_path,
    database,
    table,
    partition_columns=None,
    date_column=None
):
    # 1. Reads the JSONs from S3
    df = wr.s3.read_json(source_path)

    mode = "overwrite_partitions" if partition_columns else "overwrite"

    # 2. Extracts year and month from the date, if partitioned
    if partition_columns:
        df[date_column] = pd.to_datetime(df[date_column], errors="coerce")
        df["year"] = df[date_column].dt.year.astype("Int64").astype(str)
        df["month"] = df[date_column].dt.month.astype("Int64").astype(str).str.zfill(2)

    # 3. Saves as Parquet (partitioned if partition_columns is provided)
    wr.s3.to_parquet(
        df=df,
        path=destination_path,
        dataset=True,
        partition_cols=partition_columns if partition_columns else [],
        database=database,
        table=table,
        mode=mode
    )

    partition_values = []
    if partition_columns:
        # Get unique combinations of partition columns
        unique_partitions = df[partition_columns].drop_duplicates()
        # Build partition string for each row, e.g. "year=2023/month=01" or "custom=A"
        for _, row in unique_partitions.iterrows():
            part_str = "/".join(f"{col}={row[col]}" for col in partition_columns)
            partition_values.append(part_str)

    return {
        "processed_rows": len(df),
        "partitions": partition_values
    }

def call_glue_data_quality(job_name, database, table, partition_columns=None, partition_values=None):
    glue = boto3.client("glue")

    arguments = {
        "--DATABASE": database,
        "--TABLE": table
    }
    if partition_columns:
        arguments["--PARTITIONS"] = partition_columns
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