import sys

from awsglue.utils import getResolvedOptions
from src.utils import run_etl, REQUIRED_ARGS


def resolve_args(argv):
    """Resolve Glue job arguments required by the ETL entrypoint."""
    return getResolvedOptions(argv, REQUIRED_ARGS)


if __name__ == "__main__":
    run_etl(resolve_args(sys.argv))
    print("TMDB ETL executed successfully!")