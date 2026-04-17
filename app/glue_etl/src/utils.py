"""Funcoes utilitarias compartilhadas pela aplicacao."""

import os
from importlib import import_module

def eh_par(num):
    """Retorna True quando o numero informado e par."""
    return num % 2 == 0

def processar_numero(numero):
    """Encapsula a regra de negocio para facilitar reutilizacao e testes."""
    if eh_par(numero):
        return f"O número {numero} é par."
    else:
        return f"O número {numero} é ímpar."


def chamar_glue_data_quality(data_quality_job_name=None, glue_client=None, job_arguments=None):
    """Dispara um job do Glue Data Quality e retorna metadados da execucao."""
    if glue_client is None:
        boto3_module = import_module("boto3")
        glue_client = boto3_module.client("glue")

    data_quality_job_name = data_quality_job_name or os.getenv("GLUE_DATA_QUALITY_JOB_NAME")
    if not data_quality_job_name:
        raise ValueError("Nome do job Glue Data Quality nao informado.")

    kwargs = {"JobName": data_quality_job_name}
    if job_arguments:
        kwargs["Arguments"] = job_arguments

    response = glue_client.start_job_run(**kwargs)
    return {
        "data_quality_job_name": data_quality_job_name,
        "data_quality_job_run_id": response.get("JobRunId"),
    }
