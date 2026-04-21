import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from src.utils import obter_tmdb_api_key, carregar_filmes_tmdb_por_periodo_mensal


def lambda_handler(event, context):
    try:
        secret_arn = os.getenv("TMDB_SECRET_ARN")
        bucket_name = os.getenv("S3_BUCKET_SOR")
        bucket_aux_name = os.getenv("S3_BUCKET_AUX")

        if not secret_arn:
            raise ValueError("Variavel de ambiente TMDB_SECRET_ARN nao configurada.")

        if not bucket_name:
            raise ValueError("Variavel de ambiente S3_BUCKET_SOR nao configurada.")

        if not bucket_aux_name:
            raise ValueError("Variavel de ambiente S3_BUCKET_AUX nao configurada.")

        api_key = obter_tmdb_api_key(secret_arn)
        resumo = carregar_filmes_tmdb_por_periodo_mensal(
            api_key=api_key,
            bucket_name=bucket_name,
            data_inicio="2000-01-01",
            limite_paginas=5,
            error_bucket_name=bucket_aux_name,
            error_prefix="lambda_api/error",
        )

        return {
            "statusCode": 200,
            "body": resumo,
        }
    except Exception as e:
        return {"statusCode": 500, "body": f"Erro interno: {str(e)}"}
    

def main():
    resultado = lambda_handler(event={}, context=None)
    print(resultado)

if __name__ == "__main__":
    main()
    