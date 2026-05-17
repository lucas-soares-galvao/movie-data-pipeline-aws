
import os
from datetime import date
from src.utils import (
    extract_media_tables,
    generate_monthly_periods,
    group_periods_by_year,
    get_tmdb_key,
    process_configuration,
    process_discover,
    process_genres,
    trigger_glue_etl,
)


def lambda_handler(event, context):
    secret_arn = os.getenv("TMDB_SECRET_ARN")
    glue_job_name = os.getenv("GLUE_ETL_JOB_NAME")
    bucket = os.getenv("S3_BUCKET_SOR")

    try:
        media_info = extract_media_tables(event)
    except ValueError as error:
        return {
            "statusCode": 400,
            "body": {
                "error": str(error)
            }
        }

    api_key = get_tmdb_key(secret_arn)
    current_year = date.today().year
    periods = generate_monthly_periods(start_year=current_year)
    years_periods = group_periods_by_year(periods)

    media_type = media_info["media_type"]
    configuration_type = media_info["configuration"]

    genre_files = process_genres(api_key, bucket, media_type)
    configuration_files = process_configuration(api_key, bucket, configuration_type)

    discover_files = []
    glue_runs = []
    for year, year_periods in sorted(years_periods.items()):
        year_files = process_discover(api_key, bucket, year_periods, media_type)
        discover_files.extend(year_files)
        if year_files:
            glue = trigger_glue_etl(glue_job_name, media_info, year=year)
            glue_runs.append(glue)

    return {
        "statusCode": 200,
        "body": {
            "type": media_type,
            "discover_files": discover_files,
            "genre_files": genre_files,
            "configuration_files": configuration_files,
            "glue": glue_runs
        }
    }