"""Funcoes utilitarias compartilhadas pela aplicacao."""

import json
import os
import urllib.parse
import urllib.request
from importlib import import_module


def _normalizar_nome_chave(nome):
    return str(nome).strip().lower().replace("-", "_")

def obter_secret(secret_id=None, secrets_client=None):
    """Busca um secret no AWS Secrets Manager."""
    if secrets_client is None:
        boto3_module = import_module("boto3")
        secrets_client = boto3_module.client("secretsmanager")

    secret_id = secret_id or os.getenv("TMDB_SECRET_ARN")
    if not secret_id:
        raise ValueError("ARN do secret TMDB nao informado.")

    response = secrets_client.get_secret_value(SecretId=secret_id)
    secret_string = response.get("SecretString")
    if not secret_string:
        raise ValueError("SecretString nao encontrada no secret informado.")

    try:
        return json.loads(secret_string)
    except json.JSONDecodeError:
        return {"api_key": secret_string}


def obter_tmdb_api_key(secret_id=None, secrets_client=None):
    """Extrai uma credencial da TMDB (API key ou access token)."""
    payload = obter_secret(secret_id=secret_id, secrets_client=secrets_client)
    if not isinstance(payload, dict):
        raise ValueError("Formato invalido do secret da TMDB.")

    credencial = None

    # Campos preferenciais mais comuns.
    for key in ("api_key", "tmdb_api_key", "access_token", "tmdb_access_token"):
        valor = payload.get(key)
        if isinstance(valor, str) and valor.strip():
            credencial = valor.strip()
            break

    # Fallback para chaves com sufixos/prefixos, ex.: tmdb_api_key_dev.
    if not credencial:
        for key, valor in payload.items():
            key_normalizada = _normalizar_nome_chave(key)
            if not (isinstance(valor, str) and valor.strip()):
                continue
            if "api_key" in key_normalizada or "access_token" in key_normalizada:
                credencial = valor.strip()
                break

    if not credencial:
        raise ValueError("Credencial da TMDB nao encontrada no secret.")
    return credencial


def _is_bearer_token(credencial):
    """Identifica token JWT usado como Bearer na TMDB."""
    if not isinstance(credencial, str):
        return False
    token = credencial.strip()
    return token.count(".") == 2 and token.startswith("eyJ")


def buscar_filme_tmdb(query, api_key, timeout=10, urlopen_func=None):
    """Consulta filmes na TMDB via endpoint search/movie."""
    if not query:
        raise ValueError("Parametro query nao informado.")
    if not api_key:
        raise ValueError("TMDB API key nao informada.")

    params = urllib.parse.urlencode({"query": query, "language": "pt-BR"})
    url = f"https://api.themoviedb.org/3/search/movie?{params}"

    request = url
    if _is_bearer_token(api_key):
        request = urllib.request.Request(
            url,
            headers={
                "accept": "application/json",
                "Authorization": f"Bearer {api_key.strip()}",
            },
        )
    else:
        params_com_key = urllib.parse.urlencode(
            {
                "api_key": api_key,
                "query": query,
                "language": "pt-BR",
            }
        )
        request = f"https://api.themoviedb.org/3/search/movie?{params_com_key}"

    request_func = urlopen_func or urllib.request.urlopen

    with request_func(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


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

    concurrent_exception = None
    if hasattr(glue_client, "exceptions"):
        concurrent_exception = getattr(
            glue_client.exceptions,
            "ConcurrentRunsExceededException",
            None,
        )

    def iniciar_job(job_name):
        try:
            response = glue_client.start_job_run(JobName=job_name)
            return response.get("JobRunId"), "started"
        except Exception as exc:
            if concurrent_exception and isinstance(exc, concurrent_exception):
                return None, "already_running"
            raise

    data_quality_job_run_id, data_quality_status = iniciar_job(data_quality_job_name)
    etl_job_run_id, etl_status = iniciar_job(etl_job_name)

    return {
        "data_quality_job_name": data_quality_job_name,
        "data_quality_job_run_id": data_quality_job_run_id,
        "data_quality_job_status": data_quality_status,
        "etl_job_name": etl_job_name,
        "etl_job_run_id": etl_job_run_id,
        "etl_job_status": etl_status,
    }


def upload_arquivo_para_s3(bucket_name, file_path, s3_key, s3_client=None):
    """Faz upload de um arquivo para o bucket S3 especificado."""
    if s3_client is None:
        boto3_module = import_module("boto3")
        s3_client = boto3_module.client("s3")
    
    with open(file_path, 'rb') as f:
        s3_client.put_object(Bucket=bucket_name, Key=s3_key, Body=f)
    
    return {"bucket": bucket_name, "key": s3_key, "status": "uploaded"}
