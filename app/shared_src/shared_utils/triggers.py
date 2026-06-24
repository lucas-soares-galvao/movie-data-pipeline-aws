"""triggers.py — Função genérica para disparar jobs Glue downstream."""

import logging

import boto3

logger = logging.getLogger()


def trigger_glue_job(job_name: str, **arguments: str | None) -> str:
    """
    Dispara um job Glue sem aguardar (fire-and-forget).

    Cada chave de ``arguments`` é convertida para o formato ``--CHAVE`` esperado
    pelo Glue. Valores ``None`` são ignorados (argumentos opcionais ausentes).

    Args:
        job_name:   Nome do job registrado na AWS.
        **arguments: Argumentos do job como keyword args (ex: TABLE_NAME="tb_x", YEAR="2025").

    Returns:
        JobRunId da execução iniciada.
    """
    glue_args = {f"--{k}": str(v) for k, v in arguments.items() if v is not None}

    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(JobName=job_name, Arguments=glue_args)
    run_id = response["JobRunId"]
    logger.info(f"Job '{job_name}' iniciado. RunId: {run_id}")
    return run_id
