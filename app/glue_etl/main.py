import sys

from awsglue.utils import getResolvedOptions
from src.utils import REQUIRED_ARGS, run_etl


OPTIONAL_ARGS = [
    "TABLE_SCOPE"
]


def _resolve_optional_args(argv, optional_args):
    resolved = {}

    for arg in optional_args:
        option = f"--{arg}"
        if option in argv:
            index = argv.index(option)
            if index + 1 < len(argv):
                resolved[arg] = argv[index + 1]

    return resolved


def resolve_args(argv):
    """Resolve Glue job arguments required by the ETL entrypoint."""
    args = getResolvedOptions(argv, REQUIRED_ARGS)
    args.update(_resolve_optional_args(argv, OPTIONAL_ARGS))
    return args


if __name__ == "__main__":
    run_etl(resolve_args(sys.argv))
    print("TMDB ETL executed successfully!")