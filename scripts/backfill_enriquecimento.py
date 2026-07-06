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
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
    WAIT_SECONDS          (padrão: 60 — tempo entre runs; cada run do Glue Details dispara 2 runs do
                           Glue Data Quality em fire-and-forget, então o intervalo evita saturar o
                           max_concurrent_runs do Data Quality, compartilhado com o restante do pipeline)
    FORCE_REFETCH         (padrão: true — quando true, ignora delta mensal e re-busca todos os IDs)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

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


def _start_glue_job(
    client: Any, job_name: str, media_type: str, year: int, end_year: int, database: str, force_refetch: bool = False,
) -> str:
    """Inicia o Glue Details job e retorna o RunId."""
    arguments = {
        "--MEDIA_TYPE": media_type,
        "--YEAR": str(year),
        "--END_YEAR": str(end_year),
        "--DATABASE": database,
    }
    if force_refetch:
        arguments["--FORCE_REFETCH"] = "true"

    response = client.start_job_run(
        JobName=job_name,
        Arguments=arguments,
    )
    return response["JobRunId"]


def _wait_for_job(client: Any, job_name: str, run_id: str, poll_interval: int = 30) -> str:
    """Aguarda o Glue job terminar e retorna o estado final."""
    while True:
        try:
            response = client.get_job_run(JobName=job_name, RunId=run_id)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ExpiredTokenException":
                logger.error(
                    "Credenciais AWS expiraram durante o polling do job %s (run_id=%s). "
                    "Verifique role-duration-seconds no workflow e MaxSessionDuration da role IAM "
                    "(ver infra/docs/iam.md).",
                    job_name, run_id,
                )
            raise
        state = response["JobRun"]["JobRunState"]
        if state in ("SUCCEEDED", "FAILED", "STOPPED", "ERROR", "TIMEOUT"):
            return state
        time.sleep(poll_interval)


def main() -> None:
    region       = _require_env("AWS_REGION")
    job_name     = _require_env("GLUE_DETAILS_JOB_NAME")
    db_movie     = _require_env("GLUE_DATABASE_MOVIE")
    db_tv        = _require_env("GLUE_DATABASE_TV")

    start_year     = int(os.environ.get("BACKFILL_START_YEAR", 2000))
    end_year       = int(os.environ.get("BACKFILL_END_YEAR", datetime.now().year))
    wait_seconds   = int(os.environ.get("WAIT_SECONDS", 60))
    force_refetch  = os.environ.get("FORCE_REFETCH", "true").lower() == "true"

    client = boto3.client("glue", region_name=region)

    years = list(range(start_year, end_year + 1))
    total_runs = len(years) * 2
    logger.info(
        "Backfill de enriquecimento: %d anos (%d-%d) x 2 tipos = %d runs do Glue Details | FORCE_REFETCH=%s",
        len(years), start_year, end_year, total_runs, force_refetch,
    )

    run_count = 0
    failures: list[tuple[str, int, str]] = []
    for media_type, database in [("movie", db_movie), ("tv", db_tv)]:
        for year in years:
            run_count += 1
            logger.info(
                "[%d/%d] Disparando Glue Details | %s | year=%d",
                run_count, total_runs, media_type, year,
            )

            run_id = _start_glue_job(client, job_name, media_type, year, end_year, database, force_refetch)
            logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)

            state = _wait_for_job(client, job_name, run_id)
            if state != "SUCCEEDED":
                logger.error(
                    "Glue Details FALHOU (%s) para %s year=%d. Continuando com o próximo...",
                    state, media_type, year,
                )
                failures.append((media_type, year, state))
            else:
                logger.info("Glue Details concluído com sucesso para %s year=%d.", media_type, year)

            if run_count < total_runs:
                logger.info("Aguardando %d segundos antes do próximo run...", wait_seconds)
                time.sleep(wait_seconds)

    logger.info("Backfill de enriquecimento concluído: %d runs executados.", total_runs)
    if failures:
        logger.error(
            "%d run(s) falharam e precisam ser re-executados: %s",
            len(failures),
            ", ".join(f"{media_type}/{year} ({state})" for media_type, year, state in failures),
        )


if __name__ == "__main__":
    main()
