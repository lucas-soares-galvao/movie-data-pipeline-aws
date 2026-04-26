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


# Função genérica para discover (movie/tv)
def buscar_discover(api_key, periodo, tipo="movie", max_paginas=5):
    url = f"https://api.themoviedb.org/3/discover/{tipo}"
    idiomas = ["pt-BR", "en-US"]
    resultados = []

    for idioma in idiomas:
        resultados = []
        for pagina in range(1, max_paginas + 1):
            params = {
                "api_key": api_key,
                "sort_by": "popularity.desc",
                "page": pagina,
                "language": idioma
            }
            if tipo == "movie":
                params["primary_release_date.gte"] = periodo["data_inicio"]
                params["primary_release_date.lte"] = periodo["data_fim"]
            elif tipo == "tv":
                params["first_air_date.gte"] = periodo["data_inicio"]
                params["first_air_date.lte"] = periodo["data_fim"]

            response = requests.get(url, params=params)
            response.raise_for_status()
            dados = response.json()
            resultados.extend(dados["results"])
            if pagina >= dados.get("total_pages", 1):
                break
        if resultados:
            break
    return resultados

# Função para buscar gêneros (movie/tv)
def buscar_generos(api_key, tipo="movie"):
    url = f"https://api.themoviedb.org/3/genre/{tipo}/list"
    idiomas = ["pt-BR", "en-US"]
    for idioma in idiomas:
        params = {
            "api_key": api_key,
            "language": idioma
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        dados = response.json()
        if "genres" in dados and dados["genres"]:
            return dados["genres"]
    return []


def processar_discover(api_key, bucket, periodos, tipo):
    arquivos = []

    for periodo in periodos:
        dados = buscar_discover(api_key, periodo, tipo=tipo)

        ano = periodo["data_inicio"][:4]
        mes = periodo["data_inicio"][5:7]

        key = f"tmdb/discover/{tipo}/year={ano}/month={mes}/{tipo}_{ano}_{mes}.json"

        salvar_json_no_s3(bucket, key, dados)
        arquivos.append(key)

    return arquivos


def processar_generos(api_key, bucket, tipo):
    generos = buscar_generos(api_key, tipo=tipo)

    key = f"tmdb/genre/{tipo}/genres_{tipo}.json"

    salvar_json_no_s3(bucket, key, generos)

    return [key]


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