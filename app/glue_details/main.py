"""
main.py — Ponto de entrada do job Glue Details.

Este arquivo contém apenas a lógica principal do fluxo:
  1. Lê os argumentos do job (buckets, banco, nomes de tabelas, ARN do segredo).
  2. Busca a chave de API do TMDB no Secrets Manager.
  3. Lê os IDs distintos das tabelas de discover no SOT via Athena.
  4. Para cada ID de filme: chama /movie/{id} e grava tb_details_movie_tmdb no SOT.
  5. Para cada ID de série: chama /tv/{id} e grava tb_details_tv_tmdb no SOT.
  6. Aciona o job Glue AGG para unificar discover + detalhes na camada SPEC.

Por que este job existe?
  A Lambda API já opera no limite máximo de 900 s de timeout. Buscar detalhes
  individuais (um request por ID) adicionaria milhares de chamadas extras.
  O Glue PythonShell não tem esse limite, então a responsabilidade de coleta
  dos detalhes é delegada para cá, mantendo a Lambda enxuta.
"""

import logging
import sys

from src.utils import (
    collect_and_write_details,
    fetch_ids_from_sot,
    get_parameters_glue,
    get_tmdb_api_key,
    trigger_agg,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)


def main() -> None:
    """Coleta detalhes da API TMDB e grava no SOT. Ao final, aciona o Glue AGG."""
    args = get_parameters_glue()

    s3_bucket_sot  = args["S3_BUCKET_SOT"]
    s3_bucket_temp = args["S3_BUCKET_TEMP"]
    database       = args["DATABASE"]
    table_discover_movie = args["TABLE_DISCOVER_MOVIE"]
    table_discover_tv    = args["TABLE_DISCOVER_TV"]
    table_details_movie  = args["TABLE_DETAILS_MOVIE"]
    table_details_tv     = args["TABLE_DETAILS_TV"]
    secret_arn     = args["TMDB_SECRET_ARN"]
    agg_job_name   = args["GLUE_AGG_JOB_NAME"]
    start_year     = int(args["START_YEAR"])
    end_year       = int(args["END_YEAR"])

    # Busca a chave uma única vez — evita múltiplas chamadas ao Secrets Manager
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_tmdb_api_key(secret_arn)

    # Lê os IDs já validados do SOT (via Athena)
    movie_ids, tv_ids = fetch_ids_from_sot(
        database=database,
        table_discover_movie=table_discover_movie,
        table_discover_tv=table_discover_tv,
        s3_bucket_temp=s3_bucket_temp,
        start_year=start_year,
        end_year=end_year,
    )

    # Coleta e grava detalhes de filmes
    logger.info(f"Coletando detalhes de {len(movie_ids)} filmes...")
    collect_and_write_details(
        api_key=api_key,
        ids=movie_ids,
        content_type="movie",
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_details_movie,
        database=database,
    )

    # Coleta e grava detalhes de séries
    logger.info(f"Coletando detalhes de {len(tv_ids)} séries...")
    collect_and_write_details(
        api_key=api_key,
        ids=tv_ids,
        content_type="tv",
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_details_tv,
        database=database,
    )

    # Ambas as tabelas de detalhe estão no SOT — aciona o AGG
    logger.info("Acionando Glue AGG para unificar discover + detalhes...")
    trigger_agg(agg_job_name=agg_job_name)

    logger.info("Job Glue Details finalizado com sucesso!")


if __name__ == "__main__":
    main()
