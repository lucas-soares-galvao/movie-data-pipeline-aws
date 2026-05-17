

import json
import calendar
from datetime import date, timedelta

import requests
import boto3
import time


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

LANGUAGE_FALLBACK = ["pt-BR", "en-US"]


def get_tmdb_key(secret_arn):
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)

    secret = json.loads(response["SecretString"])
    return secret["tmdb_api_key"]


def extract_media_tables(event):
    """
    Extracts media_type, table, genre_table, and partition_columns from the event dict.
    Returns a dict with these keys.
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


def _build_discover_params(api_key, period, media_type, page, language):
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


def _request_json_with_retry(url, params, retries=3):
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


def generate_monthly_periods(start_year):
    yesterday = date.today() - timedelta(days=1)

    periods = []

    year = start_year
    month = 1

    while (year, month) <= (yesterday.year, yesterday.month):
        first_day = date(year, month, 1)

        last_day_of_month = calendar.monthrange(year, month)[1]
        last_day = date(year, month, last_day_of_month)

        # If it is the current month, goes only until yesterday
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


def group_periods_by_year(periods):
    result = {}
    for period in periods:
        year = period["start_date"][:4]
        result.setdefault(year, []).append(period)
    return result


# Generic function for discover (movie/tv)
def fetch_discover(api_key, period, media_type="movie", max_pages=5):
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

# Function to fetch genres (movie/tv)
def fetch_genres(api_key, media_type="movie"):
    url = f"https://api.themoviedb.org/3/genre/{media_type}/list"
    for language in LANGUAGE_FALLBACK:
        params = {
            "api_key": api_key,
            "language": language
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if "genres" in data and data["genres"]:
            return data["genres"]
    return []


def fetch_configuration(api_key, configuration_type="languages"):

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

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def process_discover(api_key, bucket, periods, media_type):
    files = []

    for period in periods:
        data = fetch_discover(api_key, period, media_type=media_type)

        year = period["start_date"][:4]
        month = period["start_date"][5:7]

        key = f"tmdb/discover/{media_type}/year={year}/month={month}/{media_type}_{year}_{month}.json"

        save_json_to_s3(bucket, key, data)
        files.append(key)

    return files


def process_genres(api_key, bucket, media_type):
    genres = fetch_genres(api_key, media_type=media_type)

    key = f"tmdb/genre/{media_type}/genres_{media_type}.json"

    save_json_to_s3(bucket, key, genres)

    return [key]


def process_configuration(api_key, bucket, configuration_type):
    if not configuration_type:
        return []

    configuration = fetch_configuration(api_key, configuration_type=configuration_type)

    key = f"tmdb/configuration/{configuration_type}/configuration_{configuration_type}.json"

    save_json_to_s3(bucket, key, configuration)

    return [key]


def save_json_to_s3(bucket, key, data):
    s3 = boto3.client("s3")

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data).encode("utf-8")
    )


def trigger_glue_etl(job_name, params, year=None):
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

    response = glue.start_job_run(
        JobName=job_name,
        Arguments=arguments
    )

    return {
        "job_name": job_name,
        "job_run_id": response["JobRunId"]
    }