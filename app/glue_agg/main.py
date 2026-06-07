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

logger = logging.getLogger()
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)


def main() -> None:
    """Executa o pipeline de agregação: query Athena → escrita no SPEC."""
    args = get_parameters_glue()

    s3_bucket_spec = args["S3_BUCKET_SPEC"]
    s3_bucket_temp = args["S3_BUCKET_TEMP"]
    database = args["DATABASE"]
    table_name = args["TABLE_NAME"]

    logger.info(
        f"Iniciando Glue AGG | tabela destino: '{table_name}' | banco: '{database}'"
    )

    df = run_athena_query(database=database, s3_bucket_temp=s3_bucket_temp)
    df = traduzir_colunas_en(df)
    write_parquet_to_spec(
        df=df,
        s3_bucket_spec=s3_bucket_spec,
        table_name=table_name,
        database=database,
    )

    logger.info("Job Glue AGG finalizado com sucesso!")


if __name__ == "__main__":
    main()