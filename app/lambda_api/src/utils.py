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


def chamar_glue_etl_e_data_quality(
    etl_job_name=None,
    data_quality_job_name=None,
    glue_client=None,
):
    """Dispara os jobs do Glue Data Quality e ETL e retorna seus run IDs."""
    if glue_client is None:
        boto3_module = import_module("boto3")
        glue_client = boto3_module.client("glue")

    etl_job_name = etl_job_name or os.getenv("GLUE_ETL_JOB_NAME")
    data_quality_job_name = data_quality_job_name or os.getenv("GLUE_DATA_QUALITY_JOB_NAME")

    if not etl_job_name:
        raise ValueError("Nome do job Glue ETL nao informado.")

    if not data_quality_job_name:
        raise ValueError("Nome do job Glue Data Quality nao informado.")

    data_quality_response = glue_client.start_job_run(JobName=data_quality_job_name)
    etl_response = glue_client.start_job_run(JobName=etl_job_name)

    return {
        "data_quality_job_name": data_quality_job_name,
        "data_quality_job_run_id": data_quality_response.get("JobRunId"),
        "etl_job_name": etl_job_name,
        "etl_job_run_id": etl_response.get("JobRunId"),
    }


def upload_arquivo_para_s3(bucket_name, file_path, s3_key, s3_client=None):
    """Faz upload de um arquivo para o bucket S3 especificado."""
    if s3_client is None:
        boto3_module = import_module("boto3")
        s3_client = boto3_module.client("s3")
    
    with open(file_path, 'rb') as f:
        s3_client.put_object(Bucket=bucket_name, Key=s3_key, Body=f)
    
    return {"bucket": bucket_name, "key": s3_key, "status": "uploaded"}
