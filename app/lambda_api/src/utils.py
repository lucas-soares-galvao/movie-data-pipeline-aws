"""Funcoes utilitarias compartilhadas pela aplicacao."""
import calendar
import json
from datetime import date, datetime, timedelta

import boto3
import requests


def _extrair_tmdb_credential(secret_string):
    try:
        secret_dict = json.loads(secret_string)
    except json.JSONDecodeError:
        secret_limpo = secret_string.strip()
        if not secret_limpo:
            raise RuntimeError("SecretString da TMDB esta vazio.")
        return {
            "tipo": "bearer" if "." in secret_limpo else "api_key",
            "valor": secret_limpo,
        }

    for campo in ("TMDB_API_KEY", "api_key"):
        valor = secret_dict.get(campo)
        if valor:
            return {"tipo": "api_key", "valor": valor}

    for campo in ("TMDB_READ_ACCESS_TOKEN", "TMDB_ACCESS_TOKEN", "access_token"):
        valor = secret_dict.get(campo)
        if valor:
            return {"tipo": "bearer", "valor": valor}

    raise RuntimeError(
        "Secret da TMDB deve conter TMDB_API_KEY ou TMDB_READ_ACCESS_TOKEN."
    )


def obter_tmdb_api_key(secret_arn):
    client = boto3.client("secretsmanager")

    try:
        response = client.get_secret_value(SecretId=secret_arn)
        secret = response["SecretString"]
        return _extrair_tmdb_credential(secret)
    except Exception as e:
        raise RuntimeError(f"Erro ao obter a chave da TMDB: {str(e)}")


def gerar_intervalos_mensais(data_inicio="2000-01-01", data_fim=None):
    """Retorna lista com primeiro e ultimo dia de cada mes no periodo."""
    inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date()
    fim = datetime.strptime(data_fim, "%Y-%m-%d").date() if data_fim else (date.today() - timedelta(days=1))

    if inicio > fim:
        raise ValueError("data_inicio nao pode ser maior que data_fim.")

    intervalos = []
    ano, mes = inicio.year, inicio.month

    while (ano, mes) <= (fim.year, fim.month):
        primeiro_dia = datetime(ano, mes, 1).date()
        ultimo_dia = datetime(ano, mes, calendar.monthrange(ano, mes)[1]).date()

        if ano == fim.year and mes == fim.month and fim < ultimo_dia:
            ultimo_dia = fim

        intervalos.append(
            {
                "primeiro_dia": primeiro_dia.strftime("%Y-%m-%d"),
                "ultimo_dia": ultimo_dia.strftime("%Y-%m-%d"),
            }
        )

        if mes == 12:
            ano += 1
            mes = 1
        else:
            mes += 1

    return intervalos


def buscar_filme_por_periodo_de_lancamento(api_key, periodo, limite_paginas=500):
    """Busca filmes por periodo de lancamento usando a API da TMDB com paginacao."""
    url_base = "https://api.themoviedb.org/3/discover/movie"
    headers = {"accept": "application/json"}

    if isinstance(api_key, dict):
        credencial_tmdb = api_key
    else:
        credencial_tmdb = {"tipo": "api_key", "valor": api_key}

    if not credencial_tmdb.get("valor"):
        raise RuntimeError("Credencial da TMDB nao encontrada ou vazia.")

    if credencial_tmdb.get("tipo") == "bearer":
        headers["Authorization"] = f"Bearer {credencial_tmdb['valor']}"

    try:
        filmes = []
        pagina = 1
        total_paginas_disponiveis = 1

        while pagina <= total_paginas_disponiveis and pagina <= limite_paginas:
            params = {
                "primary_release_date.gte": periodo["primeiro_dia"],
                "primary_release_date.lte": periodo["ultimo_dia"],
                "language": "pt-BR",
                "sort_by": "primary_release_date.asc",
                "page": pagina,
            }

            if credencial_tmdb.get("tipo") == "api_key":
                params["api_key"] = credencial_tmdb["valor"]

            response = requests.get(url_base, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()

            total_paginas_disponiveis = payload.get("total_pages", 1)
            filmes.extend(payload.get("results", []))
            pagina += 1

        return {
            "periodo": periodo,
            "total_paginas_disponiveis": total_paginas_disponiveis,
            "paginas_processadas": min(total_paginas_disponiveis, limite_paginas),
            "limite_paginas": limite_paginas,
            "total_filmes": len(filmes),
            "results": filmes,
        }
    except Exception as e:
        raise RuntimeError(f"Erro ao buscar filmes para o periodo {periodo}: {str(e)}")


def salvar_json_no_s3(bucket_name, object_key, payload):
    """Salva um payload JSON no S3."""
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )


def carregar_filmes_tmdb_por_periodo_mensal(api_key, bucket_name, data_inicio="2000-01-01", limite_paginas=500):
    """Processa TMDB mes a mes e salva a resposta de cada mes no S3."""
    intervalos = gerar_intervalos_mensais(data_inicio=data_inicio)
    objetos_salvos = []

    for periodo in intervalos:
        payload = buscar_filme_por_periodo_de_lancamento(
            api_key=api_key,
            periodo=periodo,
            limite_paginas=limite_paginas,
        )

        ano = periodo["primeiro_dia"][0:4]
        mes = periodo["primeiro_dia"][5:7]
        key = f"tmdb/discover_movie/year={ano}/month={mes}/movies_{ano}_{mes}.json"

        salvar_json_no_s3(bucket_name=bucket_name, object_key=key, payload=payload)
        objetos_salvos.append(key)

    return {
        "total_meses_processados": len(intervalos),
        "limite_paginas_por_consulta": limite_paginas,
        "objetos_salvos": objetos_salvos,
    }
