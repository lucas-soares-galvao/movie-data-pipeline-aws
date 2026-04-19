"""Ponto de entrada da Lambda de exemplo."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from src.utils import chamar_glue_etl_e_data_quality
from src.utils import buscar_filme_tmdb, obter_tmdb_api_key


def lambda_handler(event, context):
    """Handler simples para execucao da Lambda."""
    query = event.get("query", "Matrix")

    tmdb_result = None
    tmdb_error = None
    try:
        tmdb_api_key = obter_tmdb_api_key()
        tmdb_result = buscar_filme_tmdb(query=query, api_key=tmdb_api_key)
    except Exception as exc:
        tmdb_error = str(exc)

    glue_execucao = chamar_glue_etl_e_data_quality(
        etl_job_name=event.get("glue_etl_job_name"),
        data_quality_job_name=event.get("glue_data_quality_job_name"),
    )

    return {
        "statusCode": 200,
        "body": {
            "tmdb_query": query,
            "tmdb_result": tmdb_result,
            "tmdb_error": tmdb_error,
            "glue_execucao": glue_execucao,
        },
    }

def main():
    resultado = lambda_handler(event={}, context=None)
    print(resultado)

if __name__ == "__main__":
    main()