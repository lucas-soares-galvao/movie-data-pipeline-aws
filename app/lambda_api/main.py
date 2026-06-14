"""
Lambda API — coleta dados da API TMDB e dispara o Glue ETL.
Fluxo: EventBridge → busca API key → coleta referências → coleta discover (por ano) → dispara Glue ETL.
"""

import logging
import os
from datetime import datetime

import boto3

from src.utils import (
    collect_configuration_data,
    collect_discover_data,
    collect_genre_data,
    collect_now_playing_data,
    collect_watch_providers_ref,
    get_tmdb_api_key,
    trigger_glue_job,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TMDB_SECRET_ARN = os.environ["TMDB_SECRET_ARN"]
GLUE_ETL_JOB_NAME = os.environ["GLUE_ETL_JOB_NAME"]
S3_BUCKET_SOR = os.environ["S3_BUCKET_SOR"]


def lambda_handler(event, context):
    """Coleta dados do TMDB e dispara o Glue ETL. Payload definido em eventbridge_lambda_api.tf."""
    s3_client = boto3.client("s3")
    glue_client = boto3.client("glue")

    content_type = event["type"]

    glue_base_args = {
        "MEDIA_TYPE": content_type,
        "DATABASE": event["database"],
        "DATABASE_UNIFIED": event["database_unified"],
    }

    if content_type == "movie":
        table_genre = event["table_genre_movie"]
        table_configuration = event["table_configuration_languages"]
        table_discover = event["table_discover_movie"]
        table_watch_providers_ref = event["table_watch_providers_ref_movie"]
        table_now_playing = event.get("table_now_playing_movie")
    else:
        table_genre = event["table_genre_tv"]
        table_configuration = event["table_configuration_countries"]
        table_discover = event["table_discover_tv"]
        table_watch_providers_ref = event["table_watch_providers_ref_tv"]

    only_discover = event.get("only_discover", False)
    skip_daily = event.get("skip_daily", False)

    # Busca a API key uma vez antes do loop — Secrets Manager tem custo por chamada.
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_tmdb_api_key(TMDB_SECRET_ARN)

    current_year = datetime.now().year
    start_year   = int(event.get("start_year", current_year - 1))
    end_year     = int(event.get("end_year",   current_year))

    if not only_discover:
        logger.info(f"Coletando gêneros do TMDB para '{content_type}'...")
        collect_genre_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de gêneros...")
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="genre",
            table_name=table_genre,
        )

        logger.info(f"Coletando configurações do TMDB para '{content_type}'...")
        collect_configuration_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de configuração...")
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="configuration",
            table_name=table_configuration,
        )

        logger.info(f"Coletando referência de watch providers do TMDB para '{content_type}'...")
        collect_watch_providers_ref(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de watch providers de referência...")
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="watch_providers_ref",
            table_name=table_watch_providers_ref,
        )
    else:
        logger.info("only_discover=True: pulando coleta de genre, configuration e watch_providers_ref.")

    if skip_daily:
        logger.info("skip_daily=True: pulando coleta de discover.")
        return {
            "statusCode": 200,
            "body": f"Coleta de referência de '{content_type}' finalizada com sucesso.",
        }

    logger.info(
        f"Iniciando coleta do TMDB ({content_type}) de {start_year} até {end_year}..."
    )

    for year in range(start_year, end_year + 1):
        logger.info(f"=== Ano: {year} | Tipo: {content_type} ===")

        collect_discover_data(
            api_key=api_key,
            s3_client=s3_client,
            bucket=S3_BUCKET_SOR,
            content_type=content_type,
            folder=f"tmdb/discover/{content_type}",
            year=year,
        )

        # end_year é repassado para o Glue Details saber quando é o último run do ciclo
        # (tv + end_year → dispara o Glue AGG).
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="discover",
            table_name=table_discover,
            year=year,
            end_year=end_year,
        )

    if content_type == "movie" and table_now_playing:
        logger.info("Coletando filmes em cartaz nos cinemas...")
        collect_now_playing_data(api_key, s3_client, S3_BUCKET_SOR)
        logger.info("Acionando Glue ETL para tabela de now_playing...")
        trigger_glue_job(
            glue_client,
            GLUE_ETL_JOB_NAME,
            glue_base_args,
            table_type="now_playing",
            table_name=table_now_playing,
        )

    logger.info(f"Coleta de '{content_type}' finalizada com sucesso!")
    return {
        "statusCode": 200,
        "body": f"Dados de '{content_type}' coletados de {start_year} a {end_year} com sucesso.",
    }
