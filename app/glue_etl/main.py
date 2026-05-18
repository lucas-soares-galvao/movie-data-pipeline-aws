# Raciocinio: entrypoint ETL que resolve argumentos do Glue e delega o processamento para o modulo utilitario.

import sys

from awsglue.utils import getResolvedOptions
from src.utils import REQUIRED_ARGS, run_etl


# Argumentos opcionais passados pela Lambda ao disparar o job para um ano/escopo específico.
OPTIONAL_ARGS = [
    "TABLE_SCOPE",
    "YEAR"
]


def _resolve_optional_args(argv: list[str], optional_args: list[str]) -> dict[str, str]:
    # getResolvedOptions exige que todos os args declarados existam no argv;
    # por isso os opcionais são resolvidos manualmente para não causar erro quando ausentes.
    resolved: dict[str, str] = {}

    for arg in optional_args:
        option = f"--{arg}"
        if option in argv:
            index = argv.index(option)
            if index + 1 < len(argv):
                resolved[arg] = argv[index + 1]

    return resolved


def resolve_args(argv: list[str]) -> dict[str, str]:
    """Resolve argumentos do Glue considerando obrigatorios e opcionais.

    Raciocinio: manter validacao forte nos obrigatorios via getResolvedOptions,
    mas sem quebrar execucoes em que YEAR/TABLE_SCOPE nao foram enviados.
    """
    args = getResolvedOptions(argv, REQUIRED_ARGS)
    args.update(_resolve_optional_args(argv, OPTIONAL_ARGS))
    return args


if __name__ == "__main__":
    run_etl(resolve_args(sys.argv))
    print("TMDB ETL executed successfully!")
