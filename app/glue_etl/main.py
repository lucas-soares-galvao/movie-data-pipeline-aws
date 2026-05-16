import sys

from awsglue.utils import getResolvedOptions
from app.glue_etl.src.utils import REQUIRED_ARGS, run_etl


def resolve_args(argv):
    """Resolve Glue job arguments required by the ETL entrypoint."""
    return getResolvedOptions(argv, REQUIRED_ARGS)


if __name__ == "__main__":
    run_etl(resolve_args(sys.argv))
    print("TMDB ETL executed successfully!")