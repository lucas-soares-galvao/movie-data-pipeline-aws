"""
backfill_referencias.py — Atualiza tabelas de referência via Lambda.

Invoca a Lambda uma vez para movie e uma vez para tv com skip_discover=True,
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

import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any

import boto3

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger()


def _require_env(name: str) -> str:
    """Lê variável de ambiente obrigatória ou levanta erro."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def _invoke(client: Any, function_name: str, payload: dict[str, Any]) -> None:
    """Invoca a Lambda de forma síncrona e lança exceção se falhar."""
    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    status = response["StatusCode"]
    body = json.loads(response["Payload"].read())

    if status != 200 or "FunctionError" in response:
        raise RuntimeError(f"Lambda retornou erro: {body}")

    logger.info("Lambda OK: %s", body.get("body", body))


def main() -> None:
    region        = _require_env("AWS_REGION")
    function_name = _require_env("LAMBDA_FUNCTION_NAME")
    ano_ref       = datetime.now().year

    base_movie = {
        "type":                            "movie",
        "database":                        _require_env("GLUE_DATABASE_MOVIE"),
        "database_unified":                _require_env("GLUE_DATABASE_UNIFIED"),
        "table_discover_movie":            _require_env("TABLE_DISCOVER_MOVIE"),
        "table_genre_movie":               _require_env("TABLE_GENRE_MOVIE"),
        "table_configuration_languages":   _require_env("TABLE_CONFIGURATION_LANGUAGES"),
        "table_watch_providers_ref_movie": _require_env("TABLE_WATCH_PROVIDERS_REF_MOVIE"),
    }

    base_tv = {
        "type":                          "tv",
        "database":                      _require_env("GLUE_DATABASE_TV"),
        "database_unified":              _require_env("GLUE_DATABASE_UNIFIED"),
        "table_discover_tv":             _require_env("TABLE_DISCOVER_TV"),
        "table_genre_tv":                _require_env("TABLE_GENRE_TV"),
        "table_configuration_countries": _require_env("TABLE_CONFIGURATION_COUNTRIES"),
        "table_watch_providers_ref_tv":  _require_env("TABLE_WATCH_PROVIDERS_REF_TV"),
    }

    client       = boto3.client("lambda", region_name=region)
    wait_seconds = 60

    logger.info("Atualizando referências (genre, configuration, watch_providers_ref) — 2 invocações")

    logger.info("[1/2] movie | referências")
    _invoke(client, function_name, {**base_movie, "start_year": ano_ref, "end_year": ano_ref, "skip_discover": True})
    logger.info("Aguardando %d segundos...", wait_seconds)
    time.sleep(wait_seconds)

    logger.info("[2/2] tv    | referências")
    _invoke(client, function_name, {**base_tv, "start_year": ano_ref, "end_year": ano_ref, "skip_discover": True})

    logger.info("Referências atualizadas.")


if __name__ == "__main__":
    main()
