import sys

try:
    from awsglue.utils import getResolvedOptions
except ModuleNotFoundError:
    getResolvedOptions = None

# Local tests run with package import; AWS Glue runtime resolves src from job script path.
try:
    from app.glue_etl.src.utils import run_etl
except ModuleNotFoundError:
    from src.utils import run_etl

REQUIRED_ARGS = [
    "S3_BUCKET_SOR",
    "S3_BUCKET_SOT",
    "MEDIA_TYPE",
    "DATABASE",
    "DISCOVER_TABLE",
    "GENRE_TABLE",
    "CONFIGURATION_TABLE",
    "CONFIGURATION",
    "PARTITION_COLUMNS",
    "GLUE_DATA_QUALITY_JOB_NAME"
]

def resolve_args(argv):
    """Resolve Glue job arguments required by the ETL entrypoint."""
    if getResolvedOptions is None:
        raise ModuleNotFoundError("awsglue.utils is required to parse Glue job arguments")

    return getResolvedOptions(argv, REQUIRED_ARGS)


if __name__ == "__main__":
    run_etl(resolve_args(sys.argv))
    print("TMDB ETL executed successfully!")