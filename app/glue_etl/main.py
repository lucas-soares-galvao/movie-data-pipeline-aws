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


def _obter_arg_ou_env(nome_argumento, valor_padrao=None):
    return obter_valor_argumento(sys.argv, nome_argumento) or os.getenv(nome_argumento) or valor_padrao


def _obter_config_glue_etl():
    return {
        "s3_bucket_sor": _obter_arg_ou_env("S3_BUCKET_SOR"),
        "s3_bucket_sot": _obter_arg_ou_env("S3_BUCKET_SOT"),
        "catalog_database": _obter_arg_ou_env("GLUE_CATALOG_DATABASE"),
        "catalog_table": _obter_arg_ou_env("GLUE_CATALOG_TABLE"),
        "sor_prefix": _obter_arg_ou_env("SOR_PREFIX", "tmdb/discover_movie/"),
        "sot_prefix": _obter_arg_ou_env("SOT_PREFIX", "tmdb/movies_sot/"),
    }


def _validar_config_obrigatoria(config):
    chaves_obrigatorias = ["s3_bucket_sor", "s3_bucket_sot", "catalog_database", "catalog_table"]
    ausentes = [chave for chave in chaves_obrigatorias if not config.get(chave)]
    if ausentes:
        raise ValueError(
            "Argumentos obrigatorios ausentes. Defina --S3_BUCKET_SOR, --S3_BUCKET_SOT, "
            "--GLUE_CATALOG_DATABASE e --GLUE_CATALOG_TABLE."
        )


def main():
    config = _obter_config_glue_etl()
    _validar_config_obrigatoria(config)
    
    # Processa JSON da SOR e escreve Parquet na SOT + tabela no Glue Catalog.
    try:
        resultado_etl = carregar_sor_json_para_tabela_sot(
            s3_bucket_sor=config["s3_bucket_sor"],
            s3_bucket_sot=config["s3_bucket_sot"],
            catalog_database=config["catalog_database"],
            catalog_table=config["catalog_table"],
            sor_prefix=config["sor_prefix"],
            sot_prefix=config["sot_prefix"],
        )
        print(f"ETL SOT concluido com sucesso: {resultado_etl}")
    except Exception as e:
        print(f"Erro ao processar arquivo ETL: {str(e)}")
        raise

if __name__ == "__main__":
    main()