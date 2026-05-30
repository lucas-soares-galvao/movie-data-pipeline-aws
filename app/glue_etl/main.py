"""
main.py — Ponto de entrada do job Glue ETL.

Este arquivo contém apenas a lógica principal do fluxo:
  1. Lê os argumentos do job (buckets, tipo de mídia, nome da tabela, TABLE_TYPE).
  2. Mapeia TABLE_TYPE para as colunas de partição.
  3. Chama read_from_sor para ler os dados do SOR (dispatch por table_type).
  4. Chama write_parquet_to_sot para gravar no SOT em Parquet e atualizar o Catalog.

A Lambda aciona este job com --TABLE_TYPE em cada run:
  - "genre"         : processa a tabela de gêneros.
  - "configuration" : processa a tabela de idiomas ou países.
  - "discover"      : processa os dados paginados de discover (requer --YEAR).
"""

import logging


from src.utils import (
    get_parameters_glue,
    read_from_sor,
    write_parquet_to_sot,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_TABLE_TYPE_TO_PARTITION = {
    "discover": ["year"],
    "genre": None,
    "configuration": None,
}

_TABLE_TYPE_TO_MODE = {
    "discover": "overwrite_partitions",
    "genre": "overwrite",
    "configuration": "overwrite",
}


def run() -> None:
    """Executa o pipeline ETL: lê do SOR e grava no SOT em Parquet."""
    args = get_parameters_glue()

    s3_bucket_sor = args["S3_BUCKET_SOR"]
    s3_bucket_sot = args["S3_BUCKET_SOT"]
    media_type = args["MEDIA_TYPE"]
    database = args["DATABASE"]
    table_type = args["TABLE_TYPE"]
    table_name = args["TABLE_NAME"]
    year = args.get("YEAR")

    partition_cols = _TABLE_TYPE_TO_PARTITION[table_type]
    mode = _TABLE_TYPE_TO_MODE[table_type]

    logger.info(
        "Processando table_type=%s | media_type=%s | year=%s",
        table_type, media_type, year,
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

    logger.info("Job Glue ETL finalizado com sucesso!")


if __name__ == "__main__":
    run()
