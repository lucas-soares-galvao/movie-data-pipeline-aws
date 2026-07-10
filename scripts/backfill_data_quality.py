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
    S3_BUCKET_TEMP          (onde o checkpoint de retomada é armazenado)
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
    (backfill_shared.RETRYABLE_EXIT_CODE). O workflow renova a credencial
    e roda o script de novo — como o progresso é lido do checkpoint em S3
    (s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{TABLE_GROUP}.json), as
    execuções (tabela+ano) já submetidas são puladas.
"""

import os
import time
from typing import Any, List, Tuple

import boto3
from botocore.exceptions import ClientError

import backfill_shared as shared

logger = shared.setup_logging()


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
        shared.log_expired_token(exc, f"disparo do job DQ para '{table_name}' (year={year})")
        raise
    run_id = response["JobRunId"]
    logger.info(
        "Acionado: tabela='%s' | year=%s",
        table_name,
        year,
    )
    return run_id


def main() -> None:
    region         = shared.require_env("AWS_REGION")
    job_name       = shared.require_env("GLUE_DATA_QUALITY_JOB_NAME")
    table_group    = shared.require_env("TABLE_GROUP")
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    db_movie       = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv          = shared.require_env("GLUE_DATABASE_TV")

    start_year, end_year = shared.read_year_range()
    wait_seconds = int(os.environ.get("WAIT_SECONDS", 300))

    tables: List[Tuple[str, str]] = [
        (shared.require_env("TABLE_DISCOVER_MOVIE"),        db_movie),
        (shared.require_env("TABLE_DISCOVER_TV"),           db_tv),
        (shared.require_env("TABLE_DETAILS_MOVIE"),         db_movie),
        (shared.require_env("TABLE_DETAILS_TV"),            db_tv),
        (shared.require_env("TABLE_WATCH_PROVIDERS_MOVIE"), db_movie),
        (shared.require_env("TABLE_WATCH_PROVIDERS_TV"),    db_tv),
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

    completed = shared.load_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year)
    pendentes_total = sum(
        1 for year in years for table_name, _ in tables if f"{table_name}:{year}" not in completed
    )
    shared.log_resume_progress(logger, "execuções já concluídas", total, pendentes_total)

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
            shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)
            submeteu_algo_neste_ano = True

        if submeteu_algo_neste_ano and wait_seconds > 0 and year < end_year:
            logger.info("Ano %d concluído.", year)
            logger.info("Aguardando %ds antes do próximo ano...", wait_seconds)
            time.sleep(wait_seconds)

    shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)
    logger.info("Backfill DQ concluído: %d execuções submetidas.", submitted)


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
