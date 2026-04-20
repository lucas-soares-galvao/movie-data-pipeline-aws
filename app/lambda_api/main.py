import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from src.utils import chamar_glue_etl_e_data_quality
from src.utils import buscar_filme_tmdb, carregar_tmdb_por_ano_e_salvar_sor, obter_tmdb_api_key


def lambda_handler(event, context):
    """Handler simples para execucao da Lambda."""
    query = event.get("query")
    executar_ingestao_sor = event.get("executar_ingestao_sor", True)

    tmdb_result = None
    tmdb_error = None
    sor_ingestao = None
    sor_error = None

    try:
        tmdb_api_key = obter_tmdb_api_key()

        if query:
            tmdb_result = buscar_filme_tmdb(query=query, api_key=tmdb_api_key)

        if executar_ingestao_sor:
            sor_ingestao = carregar_tmdb_por_ano_e_salvar_sor(
                api_key=tmdb_api_key,
                bucket_name=os.getenv("S3_BUCKET_SOR"),
                ano_inicio=int(event.get("ano_inicio", 2000)),
                ano_fim=int(event.get("ano_fim", datetime.utcnow().year)),
                paginas_por_ano=int(event.get("paginas_por_ano", 1)),
                s3_prefix=event.get("s3_prefix", "tmdb/discover_movie"),
            )
    except Exception as exc:
        if query and tmdb_result is None:
            tmdb_error = str(exc)
        else:
            sor_error = str(exc)

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
            "sor_ingestao": sor_ingestao,
            "sor_error": sor_error,
            "glue_execucao": glue_execucao,
        },
    }

def main():
    resultado = lambda_handler(event={}, context=None)
    print(resultado)

if __name__ == "__main__":
    main()
    