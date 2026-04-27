
import os
from src.utils import (
    get_tmdb_key,
    extract_media_tables,
    generate_monthly_periods,
    process_discover,
    process_genres,
    trigger_glue_etl
)


def lambda_handler(event, context):
    secret_arn = os.getenv("TMDB_SECRET_ARN")
    glue_job_name = os.getenv("GLUE_ETL_JOB_NAME")
    bucket = os.getenv("S3_BUCKET_SOR")

    api_key = get_tmdb_key(secret_arn)
    periods = generate_monthly_periods(start_year=2000)

    media_info = extract_media_tables(event)
    media_type = media_info["media_type"]

    discover_files = process_discover(api_key, bucket, periods, media_type)
    genre_files = process_genres(api_key, bucket, media_type)
    all_files = discover_files + genre_files
    glue = trigger_glue_etl(glue_job_name, media_info) if all_files else None

    return {
        "statusCode": 200,
        "body": {
            "type": media_type,
            "discover_files": discover_files,
            "genre_files": genre_files,
            "glue": glue
        }
    }



if __name__ == "__main__":
    print(lambda_handler({}, None))