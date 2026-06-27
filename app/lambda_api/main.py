"""
Lambda API — coleta dados da API TMDB e dispara o Glue ETL.
Fluxo: EventBridge → busca API key → coleta referências → coleta discover (por ano) → dispara Glue ETL.
"""

import logging
import os
from datetime import datetime
from typing import Any

import boto3
from requests.exceptions import HTTPError

from src.utils import (
    collect_configuration_data,
    collect_discover_data,
    collect_genre_data,
    collect_now_playing_data,
    collect_watch_providers_ref,
    get_api_secret,
    trigger_glue_job,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Variáveis de ambiente injetadas pelo Terraform (lambda_api.tf, bloco environment da aws_lambda_function).
TMDB_SECRET_ARN = os.environ["TMDB_SECRET_ARN"]
GLUE_ETL_JOB_NAME = os.environ["GLUE_ETL_JOB_NAME"]
S3_BUCKET_SOR = os.environ["S3_BUCKET_SOR"]


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Coleta dados do TMDB e dispara o Glue ETL. Payload definido em eventbridge_lambda_api.tf."""
    s3_client = boto3.client("s3")

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

    # Flags de controle definidas no payload do EventBridge (ver eventbridge.tf):
    #   Semanal:  only_weekly_tables=True  → pula referências, roda discover + now_playing
    #   Mensal:   only_monthly_tables=True → roda referências + discover do ano anterior
    #   Anual:    only_annual_tables=True  → pula referências, roda discover (backfill histórico)
    #   Legado:   skip_weekly=True         → só referências (genre, config, watch_providers_ref)
    only_weekly_tables = event.get("only_weekly_tables", False)
    only_annual_tables = event.get("only_annual_tables", False)
    skip_weekly = event.get("skip_weekly", False)
    only_monthly_tables = event.get("only_monthly_tables", False)
    skip_reference = only_weekly_tables or only_annual_tables

    # Busca a API key uma vez antes do loop — Secrets Manager tem custo por chamada.
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_api_secret(TMDB_SECRET_ARN, "tmdb_api_key")

    current_year   = datetime.now().year
    start_year     = int(event.get("start_year", current_year))
    end_year       = int(event.get("end_year",   current_year))
    loop_end_year  = int(event.get("loop_end_year", end_year))

    if only_monthly_tables:
        start_year = current_year - 1
        end_year = current_year - 1
        loop_end_year = current_year - 1

    if not skip_reference:
        logger.info(f"Coletando gêneros do TMDB para '{content_type}'...")
        collect_genre_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de gêneros...")
        trigger_glue_job(
            GLUE_ETL_JOB_NAME,
            TABLE_TYPE="genre",
            TABLE_NAME=table_genre,
            **glue_base_args,
        )

        logger.info(f"Coletando configurações do TMDB para '{content_type}'...")
        collect_configuration_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de configuração...")
        trigger_glue_job(
            GLUE_ETL_JOB_NAME,
            TABLE_TYPE="configuration",
            TABLE_NAME=table_configuration,
            **glue_base_args,
        )

        logger.info(f"Coletando referência de watch providers do TMDB para '{content_type}'...")
        try:
            collect_watch_providers_ref(api_key, s3_client, S3_BUCKET_SOR, content_type)
            logger.info("Acionando Glue ETL para tabela de watch providers de referência...")
            trigger_glue_job(
                GLUE_ETL_JOB_NAME,
                TABLE_TYPE="watch_providers_ref",
                TABLE_NAME=table_watch_providers_ref,
                **glue_base_args,
            )
        except HTTPError:
            logger.error(
                f"Falha ao coletar watch_providers_ref para '{content_type}'. "
                "Pulando — dados anteriores no S3 permanecem válidos."
            )
    else:
        logger.info("skip_reference=True: pulando coleta de genre, configuration e watch_providers_ref.")

    if skip_weekly:
        logger.info("skip_weekly=True: pulando coleta de discover.")
        return {
            "statusCode": 200,
            "body": f"Coleta de referência de '{content_type}' finalizada com sucesso.",
        }

    logger.info(
        f"Iniciando coleta do TMDB ({content_type}) de {start_year} até {loop_end_year}..."
    )

    for year in range(start_year, loop_end_year + 1):
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
            GLUE_ETL_JOB_NAME,
            TABLE_TYPE="discover",
            TABLE_NAME=table_discover,
            YEAR=year,
            END_YEAR=end_year,
            **glue_base_args,
        )

    if content_type == "movie" and table_now_playing and not only_monthly_tables:
        logger.info("Coletando filmes em cartaz nos cinemas...")
        collect_now_playing_data(api_key, s3_client, S3_BUCKET_SOR)
        logger.info("Acionando Glue ETL para tabela de now_playing...")
        trigger_glue_job(
            GLUE_ETL_JOB_NAME,
            TABLE_TYPE="now_playing",
            TABLE_NAME=table_now_playing,
            **glue_base_args,
        )

    logger.info(f"Coleta de '{content_type}' finalizada com sucesso!")
    return {
        "statusCode": 200,
        "body": f"Dados de '{content_type}' coletados de {start_year} a {loop_end_year} com sucesso.",
    }
