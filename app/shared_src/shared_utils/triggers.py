"""triggers.py — Função genérica para disparar jobs Glue downstream."""

from __future__ import annotations

import logging

import boto3

logger = logging.getLogger()


def trigger_glue_job(job_name: str, **arguments: str | None) -> str:
    """
    Dispara um job Glue sem aguardar (fire-and-forget).

    Cada chave de ``arguments`` é convertida para o formato ``--CHAVE`` esperado
    pelo Glue. Valores ``None`` são ignorados (argumentos opcionais ausentes).

    Passa ``JobRunQueuingEnabled=True`` para que o run entre na fila em vez de
    falhar com ``ConcurrentRunsExceededException`` quando o job já está no limite
    de ``max_concurrent_runs`` — esse valor tem precedência sobre o
    ``job_run_queuing_enabled`` configurado na definição do job no Terraform, e
    sem ele o run é sempre tratado como "não populado" (queuing efetivamente
    desligado), mesmo com a definição do job dizendo o contrário.

    Args:
        job_name:   Nome do job registrado na AWS.
        **arguments: Argumentos do job como keyword args (ex: TABLE_NAME="tb_x", YEAR="2025").

    Returns:
        JobRunId da execução iniciada.
    """
    glue_args = {f"--{k}": str(v) for k, v in arguments.items() if v is not None}

    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(
        JobName=job_name, Arguments=glue_args, JobRunQueuingEnabled=True
    )
    run_id = response["JobRunId"]
    logger.info(f"Job '{job_name}' iniciado.")
    return run_id
