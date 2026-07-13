"""
backfill_enriquecimento.py — Re-busca detalhes com campos enriquecidos (elenco, diretor, keywords, etc.)

Dispara o Glue Details para cada ano/media_type, aproveitando que o delta mensal
(dt_processamento >= date_trunc('month', current_date)) considera IDs de meses
anteriores como stale — portanto todos os IDs serão re-buscados com os novos campos
do append_to_response (credits, keywords, release_dates, videos, external_ids).

Pré-requisitos:
  1. Terraform apply já executado com os novos schemas no Glue Catalog
  2. Código do Glue Details atualizado no S3 (deploy via CI ou manual)
  3. Rodar preferencialmente no início do mês (quando NENHUM ID tem dt_processamento no mês atual)

Uso:
    python scripts/backfill_enriquecimento.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    GLUE_DETAILS_JOB_NAME
    TABLE_GROUP            (identifica o checkpoint; valor "detalhes_e_providers" neste script)
    S3_BUCKET_TEMP          (onde o checkpoint de retomada é armazenado)
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
    WAIT_SECONDS          (padrão: 300 — tempo entre runs; cada run do Glue Details dispara 2 runs do
                           Glue Data Quality em fire-and-forget, então o intervalo evita saturar o
                           max_concurrent_runs do Data Quality, compartilhado com o restante do pipeline)
    FORCE_REFETCH         (padrão: true — quando true, ignora delta mensal e re-busca todos os IDs)
    TRANSLATE_PROVIDER    (padrão: "google" — grátis; volume alto por re-enriquecer o histórico
                           inteiro. "aws" usa AWS Translate, útil para testar um período menor
                           via BACKFILL_START_YEAR/BACKFILL_END_YEAR)

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken
    do S3), o script sai com exit code 75
    (backfill_shared.RETRYABLE_EXIT_CODE). O workflow renova a credencial
    e roda o script de novo — como o progresso é lido do checkpoint em S3
    (s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{TABLE_GROUP}.json), as
    unidades (ano+tipo) já concluídas com sucesso são puladas. Unidades que
    terminaram em estado diferente de SUCCEEDED não entram no checkpoint —
    continuam sendo re-tentadas em runs futuros com o mesmo range de anos.
"""

import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

import backfill_shared as shared

logger = shared.setup_logging()


def _start_glue_job(
    client: Any, job_name: str, media_type: str, year: int, end_year: int, database: str,
    force_refetch: bool = False, translate_provider: str = "google",
) -> str:
    """Inicia o Glue Details job e retorna o RunId."""
    arguments = {
        "--MEDIA_TYPE": media_type,
        "--YEAR": str(year),
        "--END_YEAR": str(end_year),
        "--DATABASE": database,
        "--TRANSLATE_PROVIDER": translate_provider,
    }
    if force_refetch:
        arguments["--FORCE_REFETCH"] = "true"

    try:
        response = client.start_job_run(
            JobName=job_name,
            Arguments=arguments,
        )
    except ClientError as exc:
        if shared.is_expired_token_error(exc):
            logger.error(
                "Credenciais AWS expiraram durante o disparo do job %s (%s/%d). O workflow "
                "vai renovar a credencial e retomar do checkpoint automaticamente "
                "(ver scripts/backfill_shared.py).",
                job_name, media_type, year,
            )
        raise
    return response["JobRunId"]


def _wait_for_job(client: Any, job_name: str, run_id: str, poll_interval: int = 30) -> str:
    """Aguarda o Glue job terminar e retorna o estado final."""
    while True:
        try:
            response = client.get_job_run(JobName=job_name, RunId=run_id)
        except ClientError as exc:
            if shared.is_expired_token_error(exc):
                logger.error(
                    "Credenciais AWS expiraram durante o polling do job %s (run_id=%s). "
                    "O workflow vai renovar a credencial e retomar do checkpoint "
                    "automaticamente (ver scripts/backfill_shared.py).",
                    job_name, run_id,
                )
            raise
        state = response["JobRun"]["JobRunState"]
        if state in ("SUCCEEDED", "FAILED", "STOPPED", "ERROR", "TIMEOUT"):
            return state
        time.sleep(poll_interval)


def main() -> None:
    region         = shared.require_env("AWS_REGION")
    job_name       = shared.require_env("GLUE_DETAILS_JOB_NAME")
    table_group    = shared.require_env("TABLE_GROUP")
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    db_movie       = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv          = shared.require_env("GLUE_DATABASE_TV")

    start_year, end_year = shared.read_year_range()
    wait_seconds  = int(os.environ.get("WAIT_SECONDS", 300))
    force_refetch = os.environ.get("FORCE_REFETCH", "true").lower() == "true"
    translate_provider = os.environ.get("TRANSLATE_PROVIDER", "google")

    client    = boto3.client("glue", region_name=region)
    s3_client = boto3.client("s3", region_name=region)

    years = list(range(start_year, end_year + 1))
    total_runs = len(years) * 2
    logger.info(
        "Backfill de enriquecimento: %d anos (%d-%d) x 2 tipos = %d runs do Glue Details | FORCE_REFETCH=%s",
        len(years), start_year, end_year, total_runs, force_refetch,
    )

    completed = shared.load_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year)

    unidades = [
        (media_type, year, database)
        for year in years
        for media_type, database in [("movie", db_movie), ("tv", db_tv)]
    ]
    pendentes = [u for u in unidades if f"{u[0]}:{u[1]}" not in completed]
    shared.log_resume_progress(logger, "runs já concluídos", len(unidades), len(pendentes))

    failures: list[tuple[str, int, str]] = []
    for i, (media_type, year, database) in enumerate(pendentes, start=1):
        logger.info(
            "[%d/%d] Disparando Glue Details | %s | year=%d",
            i, len(pendentes), media_type, year,
        )

        run_id = _start_glue_job(client, job_name, media_type, year, end_year, database, force_refetch, translate_provider)
        state = _wait_for_job(client, job_name, run_id)
        if state != "SUCCEEDED":
            logger.error(
                "Glue Details FALHOU (%s) para %s year=%d. Continuando com o próximo...",
                state, media_type, year,
            )
            failures.append((media_type, year, state))
        else:
            logger.info("Glue Details concluído com sucesso para %s year=%d.", media_type, year)
            completed.add(f"{media_type}:{year}")
            shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)

        if i < len(pendentes):
            logger.info("Aguardando %d segundos antes do próximo run...", wait_seconds)
            time.sleep(wait_seconds)

    logger.info("Backfill de enriquecimento concluído: %d runs executados.", len(pendentes))
    if failures:
        logger.error(
            "%d run(s) falharam e precisam ser re-executados: %s",
            len(failures),
            ", ".join(f"{media_type}/{year} ({state})" for media_type, year, state in failures),
        )
    else:
        shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
