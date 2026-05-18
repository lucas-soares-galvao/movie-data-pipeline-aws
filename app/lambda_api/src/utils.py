# Raciocinio: encapsula chamadas TMDB/AWS e regras de particionamento para manter o handler simples.

import json
import calendar
from datetime import date, timedelta

import requests
import boto3
import time


# Mapeamento entre tipo de mídia e as chaves esperadas no evento do EventBridge.
# Os nomes das tabelas são passados no evento porque variam entre ambientes (dev/prod).
MEDIA_EVENT_CONFIG = {
    "movie": {
        "discover_table": "table_discover_movie",
        "genre_table": "table_genre_movie",
        "configuration_table": "table_configuration_languages",
        "configuration": "languages"
    },
    "tv": {
        "discover_table": "table_discover_tv",
        "genre_table": "table_genre_tv",
        "configuration_table": "table_configuration_countries",
        "configuration": "countries"
    }
}

# A API TMDB retorna mais dados em inglês; tentamos pt-BR primeiro e usamos en-US como fallback.
LANGUAGE_FALLBACK = ["pt-BR", "en-US"]


def get_tmdb_key(secret_arn: str) -> str:
    """Le a chave da TMDB no Secrets Manager para manter credencial fora do codigo."""
    # Recupera a chave TMDB armazenada no Secrets Manager para evitar hardcode de credenciais.
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)

    secret = json.loads(response["SecretString"])
    return secret["tmdb_api_key"]


def extract_media_tables(event: dict) -> dict:
    """
    Resolve configuracao de tabelas a partir do tipo de midia recebido no evento.

    Raciocinio:
    - centraliza o mapeamento de chaves por midia em um unico ponto (movie/tv);
    - falha cedo para tipo invalido, evitando gravar dados em caminhos incorretos;
    - retorna contrato unico para o restante do fluxo da Lambda.
    """
    media_type = event.get("type", "movie")
    database = event.get("database")
    media_config = MEDIA_EVENT_CONFIG.get(media_type)

    if not media_config:
        raise ValueError(f"Unsupported media type: {media_type}")

    discover_table = event.get(media_config["discover_table"])
    genre_table = event.get(media_config["genre_table"])
    configuration_table = event.get(media_config["configuration_table"])
    configuration = media_config["configuration"] if configuration_table else ""
    partition_columns = "year,month" if discover_table else ""

    return {
        "media_type": media_type,
        "database": database,
        "discover_table": discover_table,
        "genre_table": genre_table,
        "configuration_table": configuration_table,
        "configuration": configuration,
        "partition_columns": partition_columns
    }


def _build_discover_params(
    api_key: str,
    period: dict,
    media_type: str,
    page: int,
    language: str,
) -> dict:
    """Monta query params da API discover com filtros de data por tipo de midia."""
    params = {
        "api_key": api_key,
        "sort_by": "popularity.desc",
        "page": page,
        "language": language
    }

    if media_type == "movie":
        params["primary_release_date.gte"] = period["start_date"]
        params["primary_release_date.lte"] = period["end_date"]
    elif media_type == "tv":
        params["first_air_date.gte"] = period["start_date"]
        params["first_air_date.lte"] = period["end_date"]
    else:
        raise ValueError(f"Invalid media type: {media_type}")

    return params


def _request_json_with_retry(url: str, params: dict, retries: int = 3) -> dict | list:
    # Só faz retry em HTTP 500 (erros transientes do servidor TMDB).
    # Outros erros (401, 404, 429) são propagados imediatamente — retry não ajudaria.
    # Backoff exponencial: 1s, 2s, 4s entre tentativas.
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as error:
            status_code = error.response.status_code if error.response else None
            if status_code == 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def generate_monthly_periods(start_year: int) -> list[dict]:
    """Gera janelas mensais fechadas para particionar a coleta e facilitar reruns."""
    # Usa "ontem" como limite para não incluir o dia atual, que pode ter dados incompletos.
    yesterday = date.today() - timedelta(days=1)

    periods = []

    year = start_year
    month = 1

    while (year, month) <= (yesterday.year, yesterday.month):
        first_day = date(year, month, 1)

        last_day_of_month = calendar.monthrange(year, month)[1]
        last_day = date(year, month, last_day_of_month)

        # Se for o mês atual, o end_date é ontem (não o último dia do mês).
        if year == yesterday.year and month == yesterday.month:
            last_day = yesterday

        periods.append({
            "start_date": first_day.strftime("%Y-%m-%d"),
            "end_date": last_day.strftime("%Y-%m-%d")
        })

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    return periods


def group_periods_by_year(periods: list[dict]) -> dict[str, list[dict]]:
    """Agrupa periodos por ano para disparar Glue de forma incremental anual."""
    result: dict[str, list[dict]] = {}
    for period in periods:
        year = period["start_date"][:4]
        result.setdefault(year, []).append(period)
    return result


def fetch_discover(
    api_key: str,
    period: dict,
    media_type: str = "movie",
    max_pages: int = 5,
) -> list[dict]:
    """Busca conteudo discover com fallback de idioma e limite de paginacao."""
    # Tenta pt-BR primeiro; se não retornar resultados, cai para en-US.
    # max_pages limita a paginação para evitar execuções longas em períodos muito populares.
    url = f"https://api.themoviedb.org/3/discover/{media_type}"
    for language in LANGUAGE_FALLBACK:
        results = []
        for page in range(1, max_pages + 1):
            params = _build_discover_params(api_key, period, media_type, page, language)
            data = _request_json_with_retry(url, params=params)
            results.extend(data["results"])
            if page >= data.get("total_pages", 1):
                break
        if results:
            return results
    return []


def fetch_genres(api_key: str, media_type: str = "movie") -> list[dict]:
    """Busca genero com fallback de idioma para aumentar taxa de preenchimento."""
    url = f"https://api.themoviedb.org/3/genre/{media_type}/list"
    for language in LANGUAGE_FALLBACK:
        params = {
            "api_key": api_key,
            "language": language
        }
        data = _request_json_with_retry(url, params=params)
        if "genres" in data and data["genres"]:
            return data["genres"]
    return []


def fetch_configuration(api_key: str, configuration_type: str = "languages") -> list[dict]:
    """Busca configuracoes globais da TMDB (languages/countries)."""
    url = f"https://api.themoviedb.org/3/configuration/{configuration_type}"

    if configuration_type == "languages":
        params = {
            "api_key": api_key,
            "language": "pt-BR"
        }
    elif configuration_type == "countries":
        params = {
            "api_key": api_key
        }
    else:
        raise ValueError(f"Invalid configuration type: {configuration_type}")

    return _request_json_with_retry(url, params=params)


def process_discover(
    api_key: str,
    bucket: str,
    periods: list[dict],
    media_type: str,
) -> list[str]:
    """Extrai discover por periodo e salva cada mes em chave S3 particionada por ano/mes."""
    files = []

    for period in periods:
        data = fetch_discover(api_key, period, media_type=media_type)

        year = period["start_date"][:4]
        month = period["start_date"][5:7]

        # Nome de chave deterministico para idempotencia e facil localizacao por particao temporal.
        key = f"tmdb/discover/{media_type}/year={year}/month={month}/{media_type}_{year}_{month}.json"

        save_json_to_s3(bucket, key, data)
        files.append(key)

    return files


def process_genres(api_key: str, bucket: str, media_type: str) -> list[str]:
    """Extrai genero e salva snapshot unico por tipo de midia."""
    genres = fetch_genres(api_key, media_type=media_type)

    key = f"tmdb/genre/{media_type}/genres_{media_type}.json"

    save_json_to_s3(bucket, key, genres)

    return [key]


def process_configuration(api_key: str, bucket: str, configuration_type: str) -> list[str]:
    """Extrai configuracao estatica quando aplicavel e persiste no S3."""
    if not configuration_type:
        return []

    configuration = fetch_configuration(api_key, configuration_type=configuration_type)

    key = f"tmdb/configuration/{configuration_type}/configuration_{configuration_type}.json"

    save_json_to_s3(bucket, key, configuration)

    return [key]


def save_json_to_s3(bucket: str, key: str, data: list | dict) -> None:
    # Serializa para UTF-8 antes de enviar; o Glue ETL lerá com wr.s3.read_json.
    s3 = boto3.client("s3")

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data).encode("utf-8")
    )


def trigger_glue_etl(
    job_name: str,
    params: dict,
    year: str | None = None,
    table_scope: str | None = None,
) -> dict:
    """Dispara Glue ETL com argumentos dinamicos para escopo estatico ou discover anual."""
    # Os argumentos do Glue precisam do prefixo "--" conforme convenção do AWS Glue Job.
    # year e table_scope são opcionais: omiti-los processa todos os anos/todas as tabelas.
    glue = boto3.client("glue")

    arguments = {
        "--MEDIA_TYPE": params["media_type"],
        "--DATABASE": params["database"],
        "--DISCOVER_TABLE": params["discover_table"],
        "--GENRE_TABLE": params["genre_table"],
        "--CONFIGURATION_TABLE": params["configuration_table"],
        "--CONFIGURATION": params["configuration"],
        "--PARTITION_COLUMNS": params["partition_columns"]
    }
    if year:
        arguments["--YEAR"] = year
    if table_scope:
        arguments["--TABLE_SCOPE"] = table_scope

    response = glue.start_job_run(
        JobName=job_name,
        Arguments=arguments
    )

    return {
        "job_name": job_name,
        "job_run_id": response["JobRunId"]
    }
