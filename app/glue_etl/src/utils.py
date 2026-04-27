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

    return {
        "processed_rows": len(df)
    }

def call_glue_data_quality(job_name, partition_columns=None):
    glue = boto3.client("glue")

    response = glue.start_job_run(
        JobName=job_name,
        Arguments={
            "--PARTITIONS": partition_columns if partition_columns else ""
        }
    )

    return {
        "job_name": job_name,
        "job_run_id": response["JobRunId"]
    }