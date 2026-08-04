"""
Lambda Glue Orchestrator — aguarda jobs Glue terminarem e aciona um job alvo.
Fluxo: lambda_api (invocação assíncrona) → espera os jobs de `wait_for` → aciona `target_job_name`.
"""

import logging
from typing import Any

import boto3
from shared_utils.triggers import trigger_glue_job
from src.utils import wait_for_job_runs

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Espera os jobs de `event["wait_for"]` terminarem e aciona `event["target_job_name"]`.

    Payload (enviado por app/lambda_api/main.py via invocação assíncrona, InvocationType="Event"):
        wait_for:        lista de {"job_name": str, "run_id": str} a aguardar.
        target_job_name: nome do job Glue a acionar quando todos terminarem.
        target_job_args: (opcional) argumentos repassados ao job alvo.
    """
    wait_for = event["wait_for"]
    target_job_name = event["target_job_name"]
    target_job_args = event.get("target_job_args", {})

    logger.info(f"Aguardando {len(wait_for)} job(s) Glue terminarem antes de acionar '{target_job_name}'...")
    glue_client = boto3.client("glue")
    wait_for_job_runs(glue_client, wait_for)

    logger.info(f"Todos os jobs terminaram — acionando '{target_job_name}'.")
    trigger_glue_job(target_job_name, **target_job_args)

    return {
        "statusCode": 200,
        "body": f"'{target_job_name}' acionado após {len(wait_for)} job(s) concluído(s).",
    }
