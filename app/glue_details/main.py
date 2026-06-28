"""
Glue Details — enriquece IDs do discover com detalhes da API TMDB (runtime, temporadas, streaming BR).
Roda fora da Lambda porque o volume de chamadas excede o timeout de 15 min da Lambda.
"""

import logging
import sys

from src.utils import (
    collect_and_write_details,
    collect_and_write_watch_providers,
    fetch_existing_ids_from_details,
    fetch_ids_from_sot,
    fetch_ids_stale_watch_providers,
    get_parameters_glue,
    get_api_secret,
    repair_details_duplicates,
    repair_discover_duplicates,
    repair_watch_providers_duplicates,
    trigger_glue_job,
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

    media_type     = args["MEDIA_TYPE"]
    year           = args["YEAR"]
    end_year       = args["END_YEAR"]
    force_refetch  = args["FORCE_REFETCH"]

    table_discover        = table_discover_movie        if media_type == "movie" else table_discover_tv
    table_details         = table_details_movie         if media_type == "movie" else table_details_tv
    table_watch_providers = table_watch_providers_movie if media_type == "movie" else table_watch_providers_tv

    # Busca a chave uma vez antes do loop — Secrets Manager tem custo por chamada.
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_api_secret(secret_arn, "tmdb_api_key")

    # ── DETAILS ───────────────────────────────────────────────────────────────
    # Usa o SOT (não o SOR) porque os IDs já foram deduplicados pelo Glue ETL.
    all_ids      = fetch_ids_from_sot(
        database=database,
        table_discover=table_discover,
        s3_bucket_temp=s3_bucket_temp,
        year=year,
    )

    if force_refetch:
        logger.info("FORCE_REFETCH=true — ignorando delta, re-buscando todos os IDs.")
        new_ids = all_ids
    else:
        existing_ids = fetch_existing_ids_from_details(
            database=database,
            table_details=table_details,
            s3_bucket_temp=s3_bucket_temp,
        )
        new_ids = list(set(all_ids) - set(existing_ids))

    logger.info(
        f"Details: {len(new_ids)} IDs a buscar de {len(all_ids)} no discover "
        f"({media_type}, year={year})."
    )
    if new_ids:
        collect_and_write_details(
            api_key=api_key,
            ids=new_ids,
            content_type=media_type,
            s3_bucket_sot=s3_bucket_sot,
            table_name=table_details,
            database=database,
        )

    # ── WATCH PROVIDERS ───────────────────────────────────────────────────────
    stale_ids = fetch_ids_stale_watch_providers(
        database=database,
        table_discover=table_discover,
        table_watch_providers=table_watch_providers,
        s3_bucket_temp=s3_bucket_temp,
        year=year,
    )

    logger.info(
        f"Watch providers: {len(stale_ids)} IDs para atualizar "
        f"({media_type}, year={year})."
    )
    if stale_ids:
        collect_and_write_watch_providers(
            api_key=api_key,
            ids=stale_ids,
            content_type=media_type,
            s3_bucket_sot=s3_bucket_sot,
            table_name=table_watch_providers,
            database=database,
            year=year,
        )

    trigger_glue_job(dq_job_name, TABLE_NAME=table_details, DATABASE=database, YEAR=year)

    trigger_glue_job(dq_job_name, TABLE_NAME=table_watch_providers, DATABASE=database, YEAR=year)

    # Ao final do ciclo de cada media_type, remove duplicatas intra-partição nas três tabelas
    # (movies e tvs reparados separadamente em seus respectivos runs de end_year).
    # Deduplicação cross-year é feita pelo Glue AGG via ROW_NUMBER / DENSE_RANK.
    if year == end_year:
        logger.info(
            f"Último run do ciclo ({media_type} + end_year) — "
            "reparando duplicatas na partição atual de discover, watch_providers e details..."
        )
        repair_discover_duplicates(
            database=database,
            table_discover=table_discover,
            s3_bucket_sot=s3_bucket_sot,
            year=year,
        )
        repair_watch_providers_duplicates(
            database=database,
            table_watch_providers=table_watch_providers,
            s3_bucket_sot=s3_bucket_sot,
            year=year,
        )
        repair_details_duplicates(
            database=database,
            table_details=table_details,
            s3_bucket_sot=s3_bucket_sot,
            s3_bucket_temp=s3_bucket_temp,
            year=year,
        )

    # tv + end_year é o último run do ciclo; só neste ponto todos os JOINs do AGG são possíveis.
    if media_type == "tv" and year == end_year:
        logger.info("Acionando Glue AGG...")
        trigger_glue_job(agg_job_name)

    logger.info("Job Glue Details finalizado com sucesso!")


if __name__ == "__main__":
    main()
