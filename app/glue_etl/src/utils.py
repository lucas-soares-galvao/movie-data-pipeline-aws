import awswrangler as wr
import boto3
import pandas as pd


def processar_tmdb(
    input_path,
    output_path,
    database,
    table,
    partition_cols=None
):
    # 1. Lê os JSONs do S3
    df = wr.s3.read_json(input_path)

    # 2. Extrai year e month da data, se particionado
    if partition_cols:
        df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce")
        df["year"] = df["release_date"].dt.year.astype("Int64").astype(str)
        df["month"] = df["release_date"].dt.month.astype("Int64").astype(str).str.zfill(2)

    # 3. Salva em Parquet (particionado se partition_cols informado)
    wr.s3.to_parquet(
        df=df,
        path=output_path,
        dataset=True,
        partition_cols=partition_cols if partition_cols else [],
        database=database,
        table=table,
        mode="overwrite"
    )

    return {
        "linhas_processadas": len(df)
    }


def chamar_glue_data_quality(job_name):
    glue = boto3.client("glue")

    response = glue.start_job_run(
        JobName=job_name,
        Arguments={
            "--PARTITIONS": "year,month"
        }
    )

    return {
        "job_name": job_name,
        "job_run_id": response["JobRunId"]
    }