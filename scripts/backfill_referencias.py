"""
backfill_referencias.py — Atualiza tabelas de referência via Lambda.

Invoca a Lambda uma vez para movie e uma vez para tv com skip_weekly=True,
coletando genre, configuration e watch_providers_ref. Não depende de ano.

Uso:
    python scripts/backfill_referencias.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    LAMBDA_FUNCTION_NAME
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    GLUE_DATABASE_UNIFIED
    TABLE_DISCOVER_MOVIE
    TABLE_GENRE_MOVIE
    TABLE_CONFIGURATION_LANGUAGES
    TABLE_WATCH_PROVIDERS_REF_MOVIE
    TABLE_DISCOVER_TV
    TABLE_GENRE_TV
    TABLE_CONFIGURATION_COUNTRIES
    TABLE_WATCH_PROVIDERS_REF_TV
"""

import time
from datetime import datetime

import boto3

import backfill_shared as shared

logger = shared.setup_logging()


def main() -> None:
    region        = shared.require_env("AWS_REGION")
    function_name = shared.require_env("LAMBDA_FUNCTION_NAME")
    ano_ref       = datetime.now().year

    base_movie, base_tv = shared.build_base_payloads()

    client       = boto3.client("lambda", region_name=region)
    wait_seconds = 300

    logger.info("Atualizando referências (genre, configuration, watch_providers_ref) — 2 invocações")

    logger.info("[1/2] movie | referências")
    shared.invoke_lambda_sync(client, function_name, {**base_movie, "start_year": ano_ref, "end_year": ano_ref, "skip_weekly": True})
    logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)
    time.sleep(wait_seconds)

    logger.info("[2/2] tv    | referências")
    shared.invoke_lambda_sync(client, function_name, {**base_tv, "start_year": ano_ref, "end_year": ano_ref, "skip_weekly": True})

    logger.info("Referências atualizadas.")


if __name__ == "__main__":
    main()
