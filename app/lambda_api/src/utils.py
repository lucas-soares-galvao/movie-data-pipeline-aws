import json
import calendar
from datetime import date, datetime, timedelta

import requests
import boto3


def obter_tmdb_api_key(secret_arn):
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)

    secret = json.loads(response["SecretString"])
    return secret["tmdb_api_key"]


def gerar_periodos_mensais(ano_inicio):
    ontem = date.today() - timedelta(days=1)

    periodos = []

    ano = ano_inicio
    mes = 1

    while (ano, mes) <= (ontem.year, ontem.month):
        primeiro_dia = date(ano, mes, 1)

        ultimo_dia_mes = calendar.monthrange(ano, mes)[1]
        ultimo_dia = date(ano, mes, ultimo_dia_mes)

        # Se for o mês atual, vai só até ontem
        if ano == ontem.year and mes == ontem.month:
            ultimo_dia = ontem

        periodos.append({
            "data_inicio": primeiro_dia.strftime("%Y-%m-%d"),
            "data_fim": ultimo_dia.strftime("%Y-%m-%d")
        })

        if mes == 12:
            ano += 1
            mes = 1
        else:
            mes += 1

    return periodos


def buscar_filmes_por_periodo(api_key, periodo, max_paginas=5):
    url = "https://api.themoviedb.org/3/discover/movie"

    filmes = []

    for pagina in range(1, max_paginas + 1):
        params = {
            "api_key": api_key,
            "primary_release_date.gte": periodo["data_inicio"],
            "primary_release_date.lte": periodo["data_fim"],
            "sort_by": "popularity.desc",
            "page": pagina
        }

        response = requests.get(url, params=params)
        response.raise_for_status()

        dados = response.json()

        filmes.extend(dados["results"])

        # Se não tiver mais páginas, para antes
        if pagina >= dados.get("total_pages", 1):
            break

    return filmes


def salvar_json_no_s3(bucket, key, data):
    s3 = boto3.client("s3")

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data).encode("utf-8")
    )


def chamar_glue_etl(job_name):
    glue = boto3.client("glue")

    response = glue.start_job_run(JobName=job_name)

    return {
        "job_name": job_name,
        "job_run_id": response["JobRunId"]
    }