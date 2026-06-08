"""
main.py — Ponto de entrada do job Glue AGG.

Este arquivo contém apenas a lógica principal do fluxo:
  1. Lê os argumentos do job (buckets, database, nome da tabela).
  2. Executa a query de unificação/enriquecimento no Athena via AWS Wrangler.
  3. Salva os dados particionados por media_type e year em Parquet
     no bucket SPEC via overwrite_partitions.

A query unifica os dados de discover (filmes e séries) da camada SOT
e enriquece com gêneros, idiomas e países da mesma camada.
O AWS Wrangler registra/atualiza a tabela no Glue Catalog automaticamente
ao gravar no SPEC, dispensando definição manual da tabela no Catalog.
"""

import logging
import sys

from src.utils import (
    get_parameters_glue,
    run_athena_query,
    traduzir_colunas_en,
    write_parquet_to_spec,
)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger()


def main() -> None:
    """Executa o pipeline de agregação: query Athena → escrita no SPEC."""
    args = get_parameters_glue()

    s3_bucket_spec = args["S3_BUCKET_SPEC"]
    s3_bucket_temp = args["S3_BUCKET_TEMP"]
    db_movie   = args["DB_MOVIE"]
    db_tv      = args["DB_TV"]
    db_unified = args["DB_UNIFIED"]
    table_name = args["TABLE_NAME"]

    logger.info(
        f"Iniciando Glue AGG | tabela destino: '{table_name}' | db_unified='{db_unified}'"
    )

    df = run_athena_query(
        db_movie=db_movie,
        db_tv=db_tv,
        db_unified=db_unified,
        s3_bucket_temp=s3_bucket_temp,
    )
    df = traduzir_colunas_en(df)
    write_parquet_to_spec(
        df=df,
        s3_bucket_spec=s3_bucket_spec,
        table_name=table_name,
        database=db_unified,
    )

    logger.info("Job Glue AGG finalizado com sucesso!")


if __name__ == "__main__":
    main()