

import json
import calendar
from datetime import date, datetime, timedelta

import requests
import boto3


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
    if media_type == "movie":
        table = event.get("table_movies")
        genre_table = event.get("table_genre_movie")
        configuration_table = event.get("table_configuration_languages")
        configuration = "languages" if configuration_table else ""
        partition_columns = "year,month" if table else ""
    elif media_type == "tv":
        table = event.get("table_tv")
        genre_table = event.get("table_genre_tv")
        configuration_table = event.get("table_configuration_countries")
        configuration = "countries" if configuration_table else ""
        partition_columns = "year,month" if table else ""
    else:
        table = None
        genre_table = None
        configuration_table = None
        partition_columns = ""
    return {
        "media_type": media_type,
        "database": database,
        "table": table,
        "genre_table": genre_table,
        "configuration_table": configuration_table,
        "configuration": configuration,
        "partition_columns": partition_columns
    }


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


# Generic function for discover (movie/tv)
def fetch_discover(api_key, period, media_type="movie", max_pages=5):
    url = f"https://api.themoviedb.org/3/discover/{media_type}"
    languages = ["pt-BR", "en-US"]
    results = []

    for language in languages:
        results = []
        for page in range(1, max_pages + 1):
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
                raise ValueError("Invalid media type")
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            results.extend(data["results"])
            if page >= data.get("total_pages", 1):
                break
        if results:
            break
    return results

# Function to fetch genres (movie/tv)
def fetch_genres(api_key, media_type="movie"):
    url = f"https://api.themoviedb.org/3/genre/{media_type}/list"
    languages = ["pt-BR", "en-US"]
    for language in languages:
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
    if configuration_type == "languages":
        language = "pt-BR"
        url = f"https://api.themoviedb.org/3/configuration/{configuration_type}/languages={language}"
    elif configuration_type == "countries":
        url = f"https://api.themoviedb.org/3/configuration/{configuration_type}"
    else:
        raise ValueError("Invalid configuration type")
    
    params = {
        "api_key": api_key
    }
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


def trigger_glue_etl(job_name, params):
    glue = boto3.client("glue")

    response = glue.start_job_run(
        JobName=job_name,
        Arguments={
            "--MEDIA_TYPE": params["media_type"],
            "--DATABASE": params["database"],
            "--TABLE": params["table"],
            "--GENRE_TABLE": params["genre_table"],
            "--CONFIGURATION_TABLE": params["configuration_table"],
            "--PARTITION_COLUMNS": params["partition_columns"]
        }
    )

    return {
        "job_name": job_name,
        "job_run_id": response["JobRunId"]
    }