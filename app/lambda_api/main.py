# Raciocinio: orquestra ingestao TMDB em duas fases (estatico e discover anual) para reduzir custo e facilitar rerun.

import os
from datetime import date
from typing import Any
from src.utils import (
    extract_media_tables,
    generate_monthly_periods,
    group_periods_by_year,
    get_tmdb_key,
    process_configuration,
    process_discover,
    process_genres,
    trigger_glue_etl,
)


def lambda_handler(event: dict, context: Any) -> dict:
    """Orquestra a ingestao TMDB em duas fases para reduzir custo e facilitar reprocessamento.

    Raciocinio do fluxo:
    1) processa dados estaticos uma vez (genres/configuration), pois mudam pouco;
    2) processa discover por ano para permitir rerun granular quando houver falha;
    3) dispara Glue apenas quando houve arquivos gerados, evitando execucoes vazias.
    """
    # Variáveis de ambiente injetadas pelo Terraform no recurso aws_lambda_function.
    secret_arn = os.getenv("TMDB_SECRET_ARN")
    glue_job_name = os.getenv("GLUE_ETL_JOB_NAME")
    bucket = os.getenv("S3_BUCKET_SOR")

    try:
        # Valida o tipo de mídia e extrai os nomes das tabelas do evento do EventBridge.
        media_info = extract_media_tables(event)
    except ValueError as error:
        return {
            "statusCode": 400,
            "body": {
                "error": str(error)
            }
        }

    api_key = get_tmdb_key(secret_arn)
    # Gera períodos mensais a partir do ano passado até ontem para evitar dados parciais do mês atual.
    last_year = date.today().year - 1
    periods = generate_monthly_periods(start_year=last_year)
    years_periods = group_periods_by_year(periods)

    media_type = media_info["media_type"]
    configuration_type = media_info["configuration"]

    # Dados estaticos sao processados uma vez por invocacao para evitar trabalho repetido por ano.
    genre_files = process_genres(api_key, bucket, media_type)
    configuration_files = process_configuration(api_key, bucket, configuration_type)

    discover_files = []
    glue_runs = []

    # Evita executar Glue sem payload novo; isso economiza custo e simplifica observabilidade.
    if genre_files or configuration_files:
        glue_runs.append(
            trigger_glue_etl(glue_job_name, media_info, table_scope="static")
        )

    # Segmentacao anual: melhora a recuperacao de falhas (reprocessa so o ano impactado)
    # e reduz o tempo de um rerun comparado a um job unico para toda a historia.
    for year, year_periods in sorted(years_periods.items()):
        year_files = process_discover(api_key, bucket, year_periods, media_type)
        discover_files.extend(year_files)
        if year_files:
            glue = trigger_glue_etl(
                glue_job_name,
                media_info,
                year=year,
                table_scope="discover"
            )
            glue_runs.append(glue)

    return {
        "statusCode": 200,
        "body": {
            "type": media_type,
            "discover_files": discover_files,
            "genre_files": genre_files,
            "configuration_files": configuration_files,
            "glue": glue_runs
        }
    }
