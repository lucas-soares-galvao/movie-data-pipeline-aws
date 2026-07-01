"""
backfill_historico.py — Popula as tabelas discover de 2000 até o ano atual.

Invoca a Lambda uma vez por ano para cada tipo (movie, tv), mantendo-se dentro
do timeout de 900 s por invocação. Cada invocação aciona automaticamente o
Glue ETL → Glue Details → (se último run de tv) Glue AGG.

Para popular referências (genre, configuration, watch_providers_ref) antes de
rodar o histórico, use backfill_referencias.py.

Uso:
    python scripts/backfill_historico.py

Variáveis de ambiente obrigatórias (copie de infra/terraform.tfvars ou outputs):
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

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
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


def _assert_single_year(payload: dict[str, Any]) -> None:
    """Valida que start_year == loop_end_year no payload (uma partição por invocação)."""
    sy, ley = payload["start_year"], payload["loop_end_year"]
    if sy != ley:
        raise ValueError(
            f"Backfill esperava start_year == loop_end_year, mas recebeu "
            f"start_year={sy}, loop_end_year={ley}. Corrija o loop antes de continuar."
        )


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
    region          = _require_env("AWS_REGION")
    function_name   = _require_env("LAMBDA_FUNCTION_NAME")

    start_year = int(os.environ.get("BACKFILL_START_YEAR", 2000))
    end_year   = int(os.environ.get("BACKFILL_END_YEAR",   datetime.now().year))

    # Payloads base espelhando exatamente o que o EventBridge envia (eventbridge_lambda_api.tf)
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

    client = boto3.client("lambda", region_name=region)

    wait_seconds = 300

    years = list(range(start_year, end_year + 1))
    total = len(years) * 2
    logger.info(
        "Backfill de %d até %d | %d invocações (discover movie + tv por ano)",
        start_year, end_year, total,
    )

    for i, year in enumerate(years, start=1):
        n_movie = i * 2 - 1
        logger.info("[%d/%d] movie | ano=%d", n_movie, total, year)
        payload_movie = {**base_movie, "start_year": year, "loop_end_year": year, "end_year": end_year, "only_discover": True}
        _assert_single_year(payload_movie)
        _invoke(client, function_name, payload_movie)
        logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)
        time.sleep(wait_seconds)

        n_tv = i * 2
        logger.info("[%d/%d] tv    | ano=%d", n_tv, total, year)
        payload_tv = {**base_tv, "start_year": year, "loop_end_year": year, "end_year": end_year, "only_discover": True}
        _assert_single_year(payload_tv)
        _invoke(client, function_name, payload_tv)
        if n_tv < total:
            logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)
            time.sleep(wait_seconds)

    logger.info("Backfill concluído: %d até %d", start_year, end_year)


if __name__ == "__main__":
    main()
