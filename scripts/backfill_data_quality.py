"""
backfill_data_quality.py — Aciona o job Glue Data Quality para as tabelas de
discover, details e watch_providers (movie e tv) de 2000 até o ano atual.

Apenas o job de Data Quality é acionado; nenhum outro job (ETL, Details,
Lambda) é invocado. As submissões são feitas de forma assíncrona em lotes de
10 (limite max_concurrent_runs do job), com pausa configurável entre lotes.

Uso:
    python scripts/backfill_data_quality.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    GLUE_DATA_QUALITY_JOB_NAME
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DISCOVER_MOVIE
    TABLE_DISCOVER_TV
    TABLE_DETAILS_MOVIE
    TABLE_DETAILS_TV
    TABLE_WATCH_PROVIDERS_MOVIE
    TABLE_WATCH_PROVIDERS_TV

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
    YEAR_SLEEP_SECONDS    (padrão: 300 — pausa entre anos)
"""

import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, List, Tuple

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


def _trigger_dq_job(
    client: Any,
    job_name: str,
    table_name: str,
    database: str,
    year: str,
) -> str:
    """Dispara o job Glue DQ de forma assíncrona e retorna o JobRunId."""
    response = client.start_job_run(
        JobName=job_name,
        Arguments={
            "--TABLE_NAME": table_name,
            "--DATABASE": database,
            "--YEAR": year,
        },
    )
    run_id = response["JobRunId"]
    logger.info(
        "Acionado: tabela='%s' | year=%s | RunId=%s",
        table_name,
        year,
        run_id,
    )
    return run_id


def main() -> None:
    region      = _require_env("AWS_REGION")
    job_name    = _require_env("GLUE_DATA_QUALITY_JOB_NAME")
    db_movie    = _require_env("GLUE_DATABASE_MOVIE")
    db_tv       = _require_env("GLUE_DATABASE_TV")

    start_year   = int(os.environ.get("BACKFILL_START_YEAR", 2000))
    end_year     = int(os.environ.get("BACKFILL_END_YEAR", datetime.now().year))
    year_sleep   = int(os.environ.get("YEAR_SLEEP_SECONDS", 300))

    tables: List[Tuple[str, str]] = [
        (_require_env("TABLE_DISCOVER_MOVIE"),        db_movie),
        (_require_env("TABLE_DISCOVER_TV"),           db_tv),
        (_require_env("TABLE_DETAILS_MOVIE"),         db_movie),
        (_require_env("TABLE_DETAILS_TV"),            db_tv),
        (_require_env("TABLE_WATCH_PROVIDERS_MOVIE"), db_movie),
        (_require_env("TABLE_WATCH_PROVIDERS_TV"),    db_tv),
    ]

    years = list(range(start_year, end_year + 1))
    total = len(years) * len(tables)

    logger.info(
        "Backfill DQ | anos %d–%d | %d tabelas | %d execuções | year_sleep=%ds",
        start_year,
        end_year,
        len(tables),
        total,
        year_sleep,
    )

    client = boto3.client("glue", region_name=region)
    run_ids: List[str] = []
    submitted = 0

    for year in years:
        for table_name, database in tables:
            submitted += 1
            logger.info("[%d/%d] %s | year=%s", submitted, total, table_name, year)
            run_id = _trigger_dq_job(client, job_name, table_name, database, str(year))
            run_ids.append(run_id)

        if year_sleep > 0 and year < end_year:
            logger.info("Ano %d concluído. Aguardando %ds antes do próximo ano...", year, year_sleep)
            time.sleep(year_sleep)

    logger.info("Backfill DQ concluído: %d execuções submetidas.", total)


if __name__ == "__main__":
    main()
