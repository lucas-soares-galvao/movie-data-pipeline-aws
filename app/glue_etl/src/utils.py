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


def ler_arquivo_do_s3(bucket_name, s3_key, s3_client=None):
    """Lê um arquivo do bucket S3 e retorna seu conteúdo."""
    if s3_client is None:
        boto3_module = import_module("boto3")
        s3_client = boto3_module.client("s3")
    
    response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
    conteudo = response['Body'].read().decode('utf-8')
    
    return conteudo


def escrever_arquivo_no_s3(bucket_name, s3_key, conteudo, s3_client=None):
    """Escreve um arquivo no bucket S3 especificado."""
    if s3_client is None:
        boto3_module = import_module("boto3")
        s3_client = boto3_module.client("s3")
    
    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=conteudo.encode('utf-8')
    )
    
    return {"bucket": bucket_name, "key": s3_key, "status": "written"}


def processar_arquivo_etl(conteudo_entrada):
    """Processa o conteúdo do arquivo lido do SOR e prepara para escrita no SOT."""
    # Adiciona um header indicando que foi processado pelo ETL
    conteudo_processado = f"[PROCESSADO PELO ETL]\n{conteudo_entrada}"
    return conteudo_processado


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
