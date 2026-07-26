"""triggers.py — Função genérica para disparar jobs Glue downstream."""

from __future__ import annotations

import logging
import random
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()

_CONCURRENT_RUNS_ERROR_CODE = "ConcurrentRunsExceededException"


def _calculate_wait(attempt: int) -> float:
    """Backoff exponencial com jitter: ~15s, 30s, 60s, 120s, 240s."""
    return (2 ** attempt) * 15 + random.uniform(0, 5)


def trigger_glue_job(job_name: str, max_retries: int = 5, **arguments: str | None) -> str:
    """
    Dispara um job Glue sem aguardar o fim da execução (fire-and-forget).

    Cada chave de ``arguments`` é convertida para o formato ``--CHAVE`` esperado
    pelo Glue. Valores ``None`` são ignorados (argumentos opcionais ausentes).

    Se o job já está no limite de ``max_concurrent_runs``, tenta novamente com
    backoff exponencial em vez de propagar ``ConcurrentRunsExceededException``
    na primeira tentativa. Não usamos o ``JobRunQueuingEnabled`` do
    ``start_job_run`` (que enfileiraria o run automaticamente, igual ao
    ``job_run_queuing_enabled`` já declarado nos jobs no Terraform) porque o
    Glue Python Shell (runtime fixo, Python 3.9) roda um botocore antigo demais
    para conhecer esse parâmetro — o `start_job_run` chamado por um job Python
    Shell (`glue_details` disparando `glue_data_quality`/`glue_agg`, por
    exemplo) lança ``ParamValidationError`` se ele for passado.

    Args:
        job_name:    Nome do job registrado na AWS.
        max_retries: Número máximo de tentativas antes de propagar o erro de
            concorrência excedida.
        **arguments: Argumentos do job como keyword args (ex: TABLE_NAME="tb_x", YEAR="2025").

    Returns:
        JobRunId da execução iniciada.

    Raises:
        ClientError: erro do Glue não relacionado a concorrência, ou
            ``ConcurrentRunsExceededException`` persistente após ``max_retries``.
    """
    glue_args = {f"--{k}": str(v) for k, v in arguments.items() if v is not None}
    glue_client = boto3.client("glue")

    for attempt in range(max_retries):
        try:
            response = glue_client.start_job_run(JobName=job_name, Arguments=glue_args)
            run_id = response["JobRunId"]
            logger.info(f"Job '{job_name}' iniciado.")
            return run_id
        except ClientError as e:
            is_concurrency_error = e.response["Error"]["Code"] == _CONCURRENT_RUNS_ERROR_CODE
            is_last_attempt = attempt == max_retries - 1
            if not is_concurrency_error or is_last_attempt:
                raise

            wait = _calculate_wait(attempt)
            logger.warning(
                f"Job '{job_name}' no limite de execuções concorrentes "
                f"(tentativa {attempt + 1}/{max_retries}). Aguardando {wait:.1f}s..."
            )
            time.sleep(wait)

    raise AssertionError("unreachable")  # max_retries >= 1 sempre retorna ou lança acima
