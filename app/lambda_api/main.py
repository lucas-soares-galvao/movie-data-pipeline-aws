
import os
from datetime import date, timedelta
from src.utils import (
    get_tmdb_key,
    extract_media_tables,
    generate_monthly_periods,
    process_discover,
    process_genres,
    process_configuration,
    trigger_glue_etl
)


def lambda_handler(event, context):
    secret_arn = os.getenv("TMDB_SECRET_ARN")
    glue_job_name = os.getenv("GLUE_ETL_JOB_NAME")
    bucket = os.getenv("S3_BUCKET_SOR")

    api_key = get_tmdb_key(secret_arn)
    last_year = date.today().year - 1
    periods = generate_monthly_periods(start_year=last_year)

    media_info = extract_media_tables(event)
    media_type = media_info["media_type"]
    configuration_type = media_info["configuration"]

    discover_files = process_discover(api_key, bucket, periods, media_type)
    genre_files = process_genres(api_key, bucket, media_type)
    configuration_files = process_configuration(api_key, bucket, configuration_type)
    all_files = discover_files + genre_files + configuration_files
    
    glue = trigger_glue_etl(glue_job_name, media_info) if all_files else None

    return {
        "statusCode": 200,
        "body": {
            "type": media_type,
            "discover_files": discover_files,
            "genre_files": genre_files,
            "configuration_files": configuration_files,
            "glue": glue
        }
    }



if __name__ == "__main__":
    print(lambda_handler({}, None))