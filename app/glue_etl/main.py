"""Ponto de entrada da aplicacao usada no job de Glue."""

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(__file__))
    from src.utils import (
        obter_valor_argumento,
        carregar_sor_json_para_tabela_sot,
    )
else:
    from .src.utils import (
        obter_valor_argumento,
        carregar_sor_json_para_tabela_sot,
    )


def main():
    # Configuracoes dos buckets S3 vindas dos argumentos do Glue.
    s3_bucket_sor = obter_valor_argumento(sys.argv, "S3_BUCKET_SOR") or os.getenv("S3_BUCKET_SOR")
    s3_bucket_sot = obter_valor_argumento(sys.argv, "S3_BUCKET_SOT") or os.getenv("S3_BUCKET_SOT")
    catalog_database = obter_valor_argumento(sys.argv, "GLUE_CATALOG_DATABASE") or os.getenv("GLUE_CATALOG_DATABASE")
    catalog_table = obter_valor_argumento(sys.argv, "GLUE_CATALOG_TABLE") or os.getenv("GLUE_CATALOG_TABLE")
    sor_prefix = obter_valor_argumento(sys.argv, "SOR_PREFIX") or os.getenv("SOR_PREFIX") or "tmdb/discover_movie/"
    sot_prefix = obter_valor_argumento(sys.argv, "SOT_PREFIX") or os.getenv("SOT_PREFIX") or "tmdb/movies_sot/"

    if not s3_bucket_sor or not s3_bucket_sot or not catalog_database or not catalog_table:
        raise ValueError(
            "Argumentos obrigatorios ausentes. Defina --S3_BUCKET_SOR, --S3_BUCKET_SOT, "
            "--GLUE_CATALOG_DATABASE e --GLUE_CATALOG_TABLE."
        )
    
    # Processa JSON da SOR e escreve Parquet na SOT + tabela no Glue Catalog.
    try:
        resultado_etl = carregar_sor_json_para_tabela_sot(
            s3_bucket_sor=s3_bucket_sor,
            s3_bucket_sot=s3_bucket_sot,
            catalog_database=catalog_database,
            catalog_table=catalog_table,
            sor_prefix=sor_prefix,
            sot_prefix=sot_prefix,
        )
        print(f"ETL SOT concluido com sucesso: {resultado_etl}")
    except Exception as e:
        print(f"Erro ao processar arquivo ETL: {str(e)}")
        raise

if __name__ == "__main__":
    main()