"""Funcoes utilitarias compartilhadas pela aplicacao."""
import calendar
import json
import time
from datetime import date, datetime, timedelta

import boto3
import requests


def _fazer_requisicao_tmdb_com_retry(url, headers, params, tentativas=3, timeout=30):
    ultima_excecao = None

    for tentativa in range(1, tentativas + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else None
            if status_code and 500 <= status_code < 600 and tentativa < tentativas:
                ultima_excecao = exc
                time.sleep(min(2 ** (tentativa - 1), 4))
                continue
            raise
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if tentativa < tentativas:
                ultima_excecao = exc
                time.sleep(min(2 ** (tentativa - 1), 4))
                continue
            raise

    if ultima_excecao:
        raise ultima_excecao

    raise RuntimeError("Falha ao consultar a API da TMDB sem excecao detalhada.")


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

    secret_normalizado = {
        str(chave).strip().lower(): valor
        for chave, valor in secret_dict.items()
    }

    for campo in ("tmdb_api_key", "api_key"):
        valor = secret_normalizado.get(campo)
        if valor:
            # Tokens JWT da TMDB (v4) normalmente possuem dois pontos (a.b.c).
            tipo = "bearer" if isinstance(valor, str) and valor.count(".") >= 2 else "api_key"
            return {"tipo": tipo, "valor": valor}

    for campo in ("tmdb_read_access_token", "tmdb_access_token", "access_token", "read_access_token"):
        valor = secret_normalizado.get(campo)
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
            params_base = {
                "primary_release_date.gte": periodo["primeiro_dia"],
                "primary_release_date.lte": periodo["ultimo_dia"],
                "sort_by": "popularity.desc",
                "page": pagina,
            }

            if credencial_tmdb.get("tipo") == "api_key":
                params_base["api_key"] = credencial_tmdb["valor"]

            payload = None
            ultimo_erro = None

            # Fallback de idioma para contornar instabilidades pontuais da API.
            for idioma in ("pt-BR", "en-US", None):
                params = dict(params_base)
                if idioma:
                    params["language"] = idioma

                try:
                    payload = _fazer_requisicao_tmdb_com_retry(
                        url=url_base,
                        headers=headers,
                        params=params,
                    )
                    break
                except requests.exceptions.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response else None
                    ultimo_erro = exc
                    if status_code and 500 <= status_code < 600 and idioma is not None:
                        continue
                    raise
                except requests.exceptions.RequestException as exc:
                    ultimo_erro = exc
                    if idioma is not None:
                        continue
                    raise

            if payload is None and ultimo_erro is not None:
                raise ultimo_erro

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


def carregar_filmes_tmdb_por_periodo_mensal(
    api_key,
    bucket_name,
    data_inicio="2000-01-01",
    limite_paginas=500,
    error_bucket_name=None,
    error_prefix="lambda_api/error",
):
    """Processa TMDB mes a mes e salva a resposta de cada mes no S3."""
    intervalos = gerar_intervalos_mensais(data_inicio=data_inicio)
    objetos_salvos = []
    objetos_erro = []

    for periodo in intervalos:
        ano = periodo["primeiro_dia"][0:4]
        mes = periodo["primeiro_dia"][5:7]
        try:
            payload = buscar_filme_por_periodo_de_lancamento(
                api_key=api_key,
                periodo=periodo,
                limite_paginas=limite_paginas,
            )

            key = f"tmdb/discover_movie/year={ano}/month={mes}/movies_{ano}_{mes}.json"
            salvar_json_no_s3(bucket_name=bucket_name, object_key=key, payload=payload)
            objetos_salvos.append(key)
        except Exception as exc:
            if not error_bucket_name:
                raise

            key_erro = f"{error_prefix}/year={ano}/month={mes}/error_{ano}_{mes}.json"
            payload_erro = {
                "periodo": periodo,
                "erro": str(exc),
                "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
            salvar_json_no_s3(
                bucket_name=error_bucket_name,
                object_key=key_erro,
                payload=payload_erro,
            )
            objetos_erro.append(key_erro)

    return {
        "total_meses_processados": len(intervalos),
        "total_meses_com_sucesso": len(objetos_salvos),
        "total_meses_com_erro": len(objetos_erro),
        "limite_paginas_por_consulta": limite_paginas,
        "objetos_salvos": objetos_salvos,
        "objetos_erro": objetos_erro,
    }
