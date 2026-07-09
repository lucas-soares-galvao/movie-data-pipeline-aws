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
    TABLE_GROUP            (identifica o checkpoint; valor "data_quality" neste script)
    S3_BUCKET_SOT          (onde o checkpoint de retomada é armazenado)
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
    WAIT_SECONDS    (padrão: 300 — pausa entre anos)

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken
    do S3), o script sai com exit code 75
    (backfill_checkpoint.RETRYABLE_EXIT_CODE). O workflow renova a credencial
    e roda o script de novo — como o progresso é lido do checkpoint em S3
    (s3://{S3_BUCKET_SOT}/_backfill_checkpoints/{TABLE_GROUP}.json), as
    execuções (tabela+ano) já submetidas são puladas.
"""

import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, List, Tuple

import boto3
from botocore.exceptions import ClientError

import backfill_checkpoint as checkpoint

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
    try:
        response = client.start_job_run(
            JobName=job_name,
            Arguments={
                "--TABLE_NAME": table_name,
                "--DATABASE": database,
                "--YEAR": year,
            },
        )
    except ClientError as exc:
        checkpoint.log_expired_token(exc, f"disparo do job DQ para '{table_name}' (year={year})")
        raise
    run_id = response["JobRunId"]
    logger.info(
        "Acionado: tabela='%s' | year=%s",
        table_name,
        year,
    )
    return run_id


def main() -> None:
    region        = _require_env("AWS_REGION")
    job_name      = _require_env("GLUE_DATA_QUALITY_JOB_NAME")
    table_group   = _require_env("TABLE_GROUP")
    s3_bucket_sot = _require_env("S3_BUCKET_SOT")
    db_movie      = _require_env("GLUE_DATABASE_MOVIE")
    db_tv         = _require_env("GLUE_DATABASE_TV")

    start_year   = int(os.environ.get("BACKFILL_START_YEAR", 2000))
    end_year     = int(os.environ.get("BACKFILL_END_YEAR", datetime.now().year))
    wait_seconds   = int(os.environ.get("WAIT_SECONDS", 300))

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
        "Backfill DQ | anos %d–%d | %d tabelas | %d execuções | wait_seconds=%ds",
        start_year,
        end_year,
        len(tables),
        total,
        wait_seconds,
    )

    client    = boto3.client("glue", region_name=region)
    s3_client = boto3.client("s3", region_name=region)

    completed = checkpoint.load_checkpoint(s3_client, s3_bucket_sot, table_group, start_year, end_year)
    pendentes_total = sum(
        1 for year in years for table_name, _ in tables if f"{table_name}:{year}" not in completed
    )
    if pendentes_total < total:
        logger.info(
            "%d de %d execuções já concluídas no checkpoint; retomando com %d pendente(s).",
            total - pendentes_total, total, pendentes_total,
        )

    run_ids: List[str] = []
    submitted = 0

    for year in years:
        submeteu_algo_neste_ano = False
        for table_name, database in tables:
            unit_id = f"{table_name}:{year}"
            if unit_id in completed:
                continue
            submitted += 1
            logger.info("[%d/%d] %s | year=%s", submitted, pendentes_total, table_name, year)
            run_id = _trigger_dq_job(client, job_name, table_name, database, str(year))
            run_ids.append(run_id)
            completed.add(unit_id)
            checkpoint.save_checkpoint(s3_client, s3_bucket_sot, table_group, start_year, end_year, completed)
            submeteu_algo_neste_ano = True

        if submeteu_algo_neste_ano and wait_seconds > 0 and year < end_year:
            logger.info("Ano %d concluído.", year)
            logger.info("Aguardando %ds antes do próximo ano...", wait_seconds)
            time.sleep(wait_seconds)

    checkpoint.clear_checkpoint(s3_client, s3_bucket_sot, table_group)
    logger.info("Backfill DQ concluído: %d execuções submetidas.", submitted)


if __name__ == "__main__":
    try:
        main()
    except ClientError as exc:
        codigo = checkpoint.expired_token_exit_code(exc)
        if codigo is not None:
            sys.exit(codigo)
        raise
