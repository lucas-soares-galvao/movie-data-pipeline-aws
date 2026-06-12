"""
Glue Details — enriquece IDs do discover com detalhes da API TMDB (runtime, temporadas, streaming BR).
Roda fora da Lambda porque o volume de chamadas excede o timeout de 15 min da Lambda.
"""

import logging
import sys

from src.utils import (
    collect_and_write_details,
    collect_and_write_watch_providers,
    fetch_ids_from_sot,
    get_parameters_glue,
    get_tmdb_api_key,
    trigger_agg,
    trigger_data_quality,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger()


def main() -> None:
    """Coleta detalhes da API TMDB para um media_type/ano e grava no SOT."""
    args = get_parameters_glue()

    s3_bucket_sot  = args["S3_BUCKET_SOT"]
    s3_bucket_temp = args["S3_BUCKET_TEMP"]
    database       = args["DATABASE"]
    secret_arn     = args["TMDB_SECRET_ARN"]
    agg_job_name   = args["GLUE_AGG_JOB_NAME"]
    dq_job_name    = args["GLUE_DATA_QUALITY_JOB_NAME"]

    table_discover_movie        = args["TABLE_DISCOVER_MOVIE"]
    table_discover_tv           = args["TABLE_DISCOVER_TV"]
    table_details_movie         = args["TABLE_DETAILS_MOVIE"]
    table_details_tv            = args["TABLE_DETAILS_TV"]
    table_watch_providers_movie = args["TABLE_WATCH_PROVIDERS_MOVIE"]
    table_watch_providers_tv    = args["TABLE_WATCH_PROVIDERS_TV"]

    media_type = args["MEDIA_TYPE"]
    year       = args["YEAR"]
    end_year   = args["END_YEAR"]

    table_discover        = table_discover_movie        if media_type == "movie" else table_discover_tv
    table_details         = table_details_movie         if media_type == "movie" else table_details_tv
    table_watch_providers = table_watch_providers_movie if media_type == "movie" else table_watch_providers_tv

    # Busca a chave uma vez antes do loop — Secrets Manager tem custo por chamada.
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_tmdb_api_key(secret_arn)

    # Usa o SOT (não o SOR) porque os IDs já foram deduplicados pelo Glue ETL.
    ids = fetch_ids_from_sot(
        database=database,
        table_discover=table_discover,
        s3_bucket_temp=s3_bucket_temp,
        year=year,
    )

    logger.info(f"Coletando detalhes de {len(ids)} itens ({media_type}, year={year})...")
    collect_and_write_details(
        api_key=api_key,
        ids=ids,
        content_type=media_type,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_details,
        database=database,
    )

    logger.info(f"Coletando watch providers BR de {len(ids)} itens ({media_type}, year={year})...")
    collect_and_write_watch_providers(
        api_key=api_key,
        ids=ids,
        content_type=media_type,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_watch_providers,
        database=database,
        year=year,
    )

    trigger_data_quality(
        dq_job_name=dq_job_name,
        table_name=table_details,
        database=database,
        year=year,
    )

    trigger_data_quality(
        dq_job_name=dq_job_name,
        table_name=table_watch_providers,
        database=database,
        year=year,
    )

    # tv + end_year é o último run do ciclo; só neste ponto todos os JOINs do AGG são possíveis.
    if media_type == "tv" and year == end_year:
        logger.info("Último run do ciclo (tv + end_year) — acionando Glue AGG...")
        trigger_agg(agg_job_name=agg_job_name)

    logger.info("Job Glue Details finalizado com sucesso!")


if __name__ == "__main__":
    main()
