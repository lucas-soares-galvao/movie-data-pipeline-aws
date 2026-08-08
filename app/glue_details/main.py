"""
Glue Details — enriquece IDs do discover com detalhes da API TMDB (runtime, temporadas, streaming BR).
Roda fora da Lambda porque o volume de chamadas excede o timeout de 15 min da Lambda.
"""

from shared_utils.glue_helpers import configure_glue_logging
from src.utils import (
    fetch_ids_from_changes_file,
    get_api_secret,
    get_parameters_glue,
    process_changed_ids,
    run_details_and_watch_providers_for_year,
    trigger_glue_job,
)

logger = configure_glue_logging()


def main() -> None:
    """Coleta detalhes da API TMDB para um media_type/ano (ou uma lista de IDs
    mudados via Changes API, no modo changes) e grava no SOT."""
    args = get_parameters_glue()

    s3_bucket_sot  = args["S3_BUCKET_SOT"]
    s3_bucket_temp = args["S3_BUCKET_TEMP"]
    database       = args["DATABASE"]
    secret_arn     = args["TMDB_SECRET_ARN"]
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
    translate_provider = args["TRANSLATE_PROVIDER"]
    changes_s3_path = args["CHANGES_S3_PATH"]

    table_discover        = table_discover_movie        if media_type == "movie" else table_discover_tv
    table_details         = table_details_movie         if media_type == "movie" else table_details_tv
    table_watch_providers = table_watch_providers_movie if media_type == "movie" else table_watch_providers_tv

    # Busca a chave uma vez antes do loop — Secrets Manager tem custo por chamada.
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_api_secret(secret_arn, "tmdb_api_key")

    # ── MODO CHANGES (Changes API do TMDB) ───────────────────────────────────
    # Acionado pela lambda_api (only_changes_tables) — não passa YEAR/END_YEAR,
    # passa CHANGES_S3_PATH com a lista de IDs mudados. Não escreve na tabela
    # discover (nunca expande o catálogo).
    if changes_s3_path:
        changed_ids = fetch_ids_from_changes_file(changes_s3_path)
        affected_years = process_changed_ids(
            api_key=api_key,
            database=database,
            table_discover=table_discover,
            table_details=table_details,
            table_watch_providers=table_watch_providers,
            content_type=media_type,
            changed_ids=changed_ids,
            s3_bucket_sot=s3_bucket_sot,
            s3_bucket_temp=s3_bucket_temp,
            translate_provider=translate_provider,
        )
        # Um disparo por tabela com todos os anos agrupados (não um disparo por ano):
        # o DQ paga o overhead fixo de startup do Spark uma vez só, iterando os anos
        # internamente, em vez de N vezes (um changes-run pode afetar dezenas de anos
        # distintos, já que edição de metadado no TMDB não correlaciona com o ano de
        # lançamento do título).
        if affected_years:
            years_arg = ",".join(affected_years)
            trigger_glue_job(dq_job_name, TABLE_NAME=table_details, DATABASE=database, YEAR=years_arg)
            trigger_glue_job(dq_job_name, TABLE_NAME=table_watch_providers, DATABASE=database, YEAR=years_arg)

        logger.info("Job Glue Details (modo changes) finalizado com sucesso!")
        return

    # ── DETAILS + WATCH PROVIDERS ────────────────────────────────────────────
    # Usa o SOT (não o SOR) porque os IDs já foram deduplicados pelo Glue ETL.
    # Orquestração completa (delta, coleta, DQ por unidade, repair de duplicatas
    # em year == end_year) vive em run_details_and_watch_providers_for_year, para
    # ser reutilizável fora do runtime do Glue — ver scripts/backfill_enriquecimento.py.
    run_details_and_watch_providers_for_year(
        api_key=api_key,
        database=database,
        media_type=media_type,
        year=year,
        end_year=end_year,
        s3_bucket_sot=s3_bucket_sot,
        s3_bucket_temp=s3_bucket_temp,
        table_discover=table_discover,
        table_details=table_details,
        table_watch_providers=table_watch_providers,
        dq_job_name=dq_job_name,
        force_refetch=force_refetch,
        translate_provider=translate_provider,
    )

    logger.info("Job Glue Details finalizado com sucesso!")


if __name__ == "__main__":
    main()
