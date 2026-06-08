"""
main.py — Ponto de entrada do job Glue ETL.

Este arquivo contém apenas a lógica principal do fluxo:
  1. Lê os argumentos do job (buckets, tipo de mídia, nome da tabela, TABLE_TYPE).
  2. Mapeia TABLE_TYPE para as colunas de partição.
  3. Chama read_from_sor para ler os dados do SOR (dispatch por table_type).
  4. Chama write_parquet_to_sot para gravar no SOT em Parquet e atualizar o Catalog.
  5. Aciona o job Glue Data Quality para validar a tabela recém-escrita.
  6. Se media_type="tv" e table_type="discover", aciona o Glue Details para buscar
     runtime/temporadas via API TMDB. O Glue Details, ao concluir, aciona o Glue AGG.

A Lambda aciona este job com --TABLE_TYPE em cada run:
  - "genre"         : processa a tabela de gêneros.
  - "configuration" : processa a tabela de idiomas ou países.
  - "discover"      : processa os dados paginados de discover (requer --YEAR).
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

# Tabelas de dispatch: mapeiam table_type para o comportamento de escrita no SOT.
# "discover" usa overwrite_partitions (sobrescreve só o ano recebido, preservando os demais).
# Os demais tipos sobrescrevem a tabela inteira a cada run, pois não têm partição.
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
    """Executa o pipeline ETL: lê do SOR e grava no SOT em Parquet."""
    args = get_parameters_glue()

    s3_bucket_sor = args["S3_BUCKET_SOR"]
    s3_bucket_sot = args["S3_BUCKET_SOT"]
    media_type = args["MEDIA_TYPE"]
    database          = args["DATABASE"]
    table_type = args["TABLE_TYPE"]
    table_name = args["TABLE_NAME"]
    dq_job_name      = args["GLUE_DATA_QUALITY_JOB_NAME"]
    details_job_name = args["GLUE_DETAILS_JOB_NAME"]
    year       = args.get("YEAR")
    end_year   = args.get("END_YEAR")

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

    # Dispara o Details em todo run de discover — um run por media_type/ano.
    # O Glue Details coleta runtime/temporadas via API TMDB para o ano recebido
    # e aciona o AGG apenas no último run (tv + end_year), quando todos os
    # detalhes de filmes e séries já estão no SOT.
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