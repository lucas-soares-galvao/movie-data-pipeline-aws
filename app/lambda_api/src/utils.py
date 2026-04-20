"""Funcoes utilitarias compartilhadas pela aplicacao."""

from collections import defaultdict
import calendar
from datetime import datetime
import json
import os
import urllib.parse
import urllib.request
from importlib import import_module


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
    """Extrai a credencial da TMDB do secret."""
    payload = obter_secret(secret_id=secret_id, secrets_client=secrets_client)
    credencial = payload.get("tmdb_api_key") or payload.get("api_key")
    if not isinstance(credencial, str) or not credencial.strip():
        raise ValueError("Credencial da TMDB nao encontrada no secret.")
    return credencial.strip()


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


def buscar_filmes_tmdb_por_ano(ano, api_key, page=1, timeout=10, urlopen_func=None):
    """Consulta filmes na TMDB por ano de lancamento via endpoint discover/movie."""
    if not ano:
        raise ValueError("Parametro ano nao informado.")
    if not api_key:
        raise ValueError("TMDB API key nao informada.")

    params = urllib.parse.urlencode(
        {
            "primary_release_year": ano,
            "page": page,
            "language": "pt-BR",
            "sort_by": "primary_release_date.asc",
        }
    )
    url = f"https://api.themoviedb.org/3/discover/movie?{params}"

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
                "primary_release_year": ano,
                "page": page,
                "language": "pt-BR",
                "sort_by": "primary_release_date.asc",
            }
        )
        request = f"https://api.themoviedb.org/3/discover/movie?{params_com_key}"

    request_func = urlopen_func or urllib.request.urlopen

    with request_func(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def buscar_filmes_tmdb_por_ano_mes(
    ano,
    mes,
    api_key,
    page=1,
    sort_by="popularity.desc",
    timeout=10,
    urlopen_func=None,
):
    """Consulta filmes na TMDB por faixa de lancamento no ano e mes."""
    if not ano:
        raise ValueError("Parametro ano nao informado.")
    if not mes:
        raise ValueError("Parametro mes nao informado.")
    if not api_key:
        raise ValueError("TMDB API key nao informada.")

    ultimo_dia = calendar.monthrange(int(ano), int(mes))[1]
    data_inicio = f"{int(ano):04d}-{int(mes):02d}-01"
    data_fim = f"{int(ano):04d}-{int(mes):02d}-{ultimo_dia:02d}"

    params = urllib.parse.urlencode(
        {
            "primary_release_date.gte": data_inicio,
            "primary_release_date.lte": data_fim,
            "page": page,
            "language": "pt-BR",
            "sort_by": sort_by,
        }
    )
    url = f"https://api.themoviedb.org/3/discover/movie?{params}"

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
                "primary_release_date.gte": data_inicio,
                "primary_release_date.lte": data_fim,
                "page": page,
                "language": "pt-BR",
                "sort_by": sort_by,
            }
        )
        request = f"https://api.themoviedb.org/3/discover/movie?{params_com_key}"

    request_func = urlopen_func or urllib.request.urlopen

    with request_func(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _particionar_filmes_por_ano_mes(filmes):
    """Agrupa filmes por particao year=YYYY/month=MM usando release_date."""
    particoes = defaultdict(list)

    for filme in filmes:
        release_date = (filme or {}).get("release_date", "")
        if not isinstance(release_date, str) or len(release_date) < 7:
            continue

        ano = release_date[0:4]
        mes = release_date[5:7]
        if not (ano.isdigit() and mes.isdigit()):
            continue

        particoes[(ano, mes)].append(filme)

    return particoes


def salvar_json_em_s3(bucket_name, s3_key, payload, s3_client=None):
    """Salva um payload JSON no S3."""
    if s3_client is None:
        boto3_module = import_module("boto3")
        s3_client = boto3_module.client("s3")

    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )


def carregar_tmdb_por_ano_e_salvar_sor(
    api_key,
    bucket_name,
    ano_inicio=2000,
    ano_fim=None,
    paginas_por_ano=1,
    paginas_por_mes=None,
    max_total_paginas=None,
    sort_by="popularity.desc",
    s3_prefix="tmdb/discover_movie",
    timeout=10,
    urlopen_func=None,
    s3_client=None,
    buscar_por_ano_func=None,
    buscar_por_ano_mes_func=None,
):
    """Busca filmes por ano na TMDB e grava no S3 em particoes year/month.

    Se paginas_por_ano <= 0, busca automaticamente todas as paginas disponiveis
    do ano (limitado a 500, limite da API da TMDB).
    Se max_total_paginas for informado, interrompe a coleta ao atingir o limite.
    """
    if not api_key:
        raise ValueError("TMDB API key nao informada.")
    if not bucket_name:
        raise ValueError("Bucket S3 SOR nao informado.")

    ano_fim = ano_fim or datetime.utcnow().year
    if ano_inicio > ano_fim:
        raise ValueError("ano_inicio nao pode ser maior que ano_fim.")
    if max_total_paginas is not None and max_total_paginas <= 0:
        raise ValueError("max_total_paginas deve ser maior que zero.")

    paginas_por_mes = paginas_por_mes if paginas_por_mes is not None else paginas_por_ano
    buscar_mes_func = buscar_por_ano_mes_func or buscar_filmes_tmdb_por_ano_mes
    filmes_coletados = []
    paginas_processadas = 0
    objetos_gravados = 0

    for ano in range(ano_inicio, ano_fim + 1):
        for mes in range(1, 13):
            if max_total_paginas is not None and paginas_processadas >= max_total_paginas:
                break

            primeira_pagina = buscar_mes_func(
                ano=ano,
                mes=mes,
                api_key=api_key,
                page=1,
                sort_by=sort_by,
                timeout=timeout,
                urlopen_func=urlopen_func,
            )
            filmes_mes = list(primeira_pagina.get("results", []))
            paginas_processadas += 1
            total_pages = int(primeira_pagina.get("total_pages", 1) or 1)
            total_pages = max(1, min(total_pages, 500))

            if paginas_por_mes <= 0:
                limite_paginas = total_pages
            else:
                limite_paginas = min(paginas_por_mes, total_pages)

            for pagina in range(2, limite_paginas + 1):
                if max_total_paginas is not None and paginas_processadas >= max_total_paginas:
                    break

                response = buscar_mes_func(
                    ano=ano,
                    mes=mes,
                    api_key=api_key,
                    page=pagina,
                    sort_by=sort_by,
                    timeout=timeout,
                    urlopen_func=urlopen_func,
                )
                filmes_mes.extend(response.get("results", []))
                paginas_processadas += 1

            if filmes_mes:
                filmes_coletados.extend(filmes_mes)
                ano_str = f"{ano:04d}"
                mes_str = f"{mes:02d}"
                s3_key = f"{s3_prefix}/year={ano_str}/month={mes_str}/movies_{ano_str}_{mes_str}.json"
                payload = {
                    "year": ano_str,
                    "month": mes_str,
                    "sort_by": sort_by,
                    "total_movies": len(filmes_mes),
                    "items": filmes_mes,
                }
                salvar_json_em_s3(
                    bucket_name=bucket_name,
                    s3_key=s3_key,
                    payload=payload,
                    s3_client=s3_client,
                )
                objetos_gravados += 1

        if max_total_paginas is not None and paginas_processadas >= max_total_paginas:
            break

    return {
        "bucket": bucket_name,
        "s3_prefix": s3_prefix,
        "ano_inicio": ano_inicio,
        "ano_fim": ano_fim,
        "paginas_por_ano": paginas_por_ano,
        "paginas_por_mes": paginas_por_mes,
        "sort_by": sort_by,
        "max_total_paginas": max_total_paginas,
        "paginas_processadas": paginas_processadas,
        "filmes_encontrados": len(filmes_coletados),
        "particoes_geradas": objetos_gravados,
        "objetos_s3_gravados": objetos_gravados,
    }


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
