"""
Glue ETL — transforma JSON do SOR em Parquet no SOT e dispara jobs downstream.

"discover" usa overwrite_partitions para preservar anos anteriores ao atualizar
um único ano; os demais tipos usam overwrite simples.
"""

import logging
import sys

from src.utils import (
    get_parameters_glue,
    read_from_sor,
    trigger_data_quality,
    trigger_details,
    write_parquet_to_sot,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger()

_TABLE_TYPE_TO_PARTITION = {
    "discover":            ["year"],
    "genre":               None,
    "configuration":       None,
    "watch_providers_ref": None,
}

_TABLE_TYPE_TO_MODE = {
    "discover":            "overwrite_partitions",
    "genre":               "overwrite",
    "configuration":       "overwrite",
    "watch_providers_ref": "overwrite",
}


def main() -> None:
    """
    Função principal do job Glue ETL.

    Lê argumentos → lê dados do SOR → grava Parquet no SOT → dispara jobs downstream.
    """
    args = get_parameters_glue()

    s3_bucket_sor    = args["S3_BUCKET_SOR"]
    s3_bucket_sot    = args["S3_BUCKET_SOT"]
    media_type       = args["MEDIA_TYPE"]
    database         = args["DATABASE"]
    table_type       = args["TABLE_TYPE"]
    table_name       = args["TABLE_NAME"]
    dq_job_name      = args["GLUE_DATA_QUALITY_JOB_NAME"]
    details_job_name = args["GLUE_DETAILS_JOB_NAME"]
    year             = args.get("YEAR")
    end_year         = args.get("END_YEAR")

    partition_cols = _TABLE_TYPE_TO_PARTITION[table_type]
    mode = _TABLE_TYPE_TO_MODE[table_type]

    logger.info(
        f"Processando table_type={table_type} | media_type={media_type} | year={year}"
    )

    df = read_from_sor(s3_bucket_sor, media_type, table_type, year)

    write_parquet_to_sot(
        df=df,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_name,
        database=database,
        partition_cols=partition_cols,
        mode=mode,
    )

    trigger_data_quality(
        dq_job_name=dq_job_name,
        table_name=table_name,
        database=database,
        year=year,
    )

    if table_type == "discover":
        trigger_details(
            details_job_name=details_job_name,
            media_type=media_type,
            year=year,
            end_year=end_year,
            database=database,
        )

    logger.info("Job Glue ETL finalizado com sucesso!")


if __name__ == "__main__":
    main()
