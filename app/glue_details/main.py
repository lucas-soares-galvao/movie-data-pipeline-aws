"""
main.py — Ponto de entrada do job Glue Details.

Este arquivo contém apenas a lógica principal do fluxo:
  1. Lê os argumentos do job (buckets, banco, nomes de tabelas, ARN do segredo,
     media_type, year, end_year).
  2. Busca a chave de API do TMDB no Secrets Manager.
  3. Lê os IDs distintos da tabela de discover do media_type/ano recebido via Athena.
  4. Chama /movie/{id} ou /tv/{id} para cada ID e grava os detalhes no SOT.
  5. Aciona o job Glue AGG somente se media_type="tv" e year == end_year,
     garantindo que todos os detalhes de filmes e séries já estão no SOT.

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
    trigger_data_quality,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)


def main() -> None:
    """Coleta detalhes da API TMDB para um media_type/ano e grava no SOT."""
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
    dq_job_name    = args["GLUE_DATA_QUALITY_JOB_NAME"]
    media_type     = args["MEDIA_TYPE"]
    year           = args["YEAR"]
    end_year       = args["END_YEAR"]

    table_discover = table_discover_movie if media_type == "movie" else table_discover_tv
    table_details  = table_details_movie  if media_type == "movie" else table_details_tv

    # Busca a chave uma única vez — evita múltiplas chamadas ao Secrets Manager
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_tmdb_api_key(secret_arn)

    # Lê os IDs já validados do SOT (via Athena) para o media_type/ano recebido
    ids = fetch_ids_from_sot(
        database=database,
        table_discover=table_discover,
        s3_bucket_temp=s3_bucket_temp,
        year=year,
    )

    logger.info(f"Coletando detalhes de {len(ids)} itens ({media_type}, year={year})...")
    collect_and_write_details(
        api_key=api_key,
        ids=ids,
        content_type=media_type,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_details,
        database=database,
    )
    trigger_data_quality(
        dq_job_name=dq_job_name,
        table_name=table_details,
        database=database,
        year=year,
    )

    # Aciona o AGG somente no último run do ciclo: tv + ano mais recente
    if media_type == "tv" and year == end_year:
        logger.info("Último run do ciclo (tv + end_year) — acionando Glue AGG...")
        trigger_agg(agg_job_name=agg_job_name)

    logger.info("Job Glue Details finalizado com sucesso!")


if __name__ == "__main__":
    main()
