import os
from src.utils import (
    obter_tmdb_api_key,
    gerar_periodos_mensais,
    processar_discover,
    processar_generos,
    chamar_glue_etl
)


def lambda_handler(event, context):
    secret_arn = os.getenv("TMDB_SECRET_ARN")
    bucket = os.getenv("S3_BUCKET_SOR")
    glue_job = os.getenv("GLUE_ETL_JOB_NAME")

    api_key = obter_tmdb_api_key(secret_arn)
    periodos = gerar_periodos_mensais(ano_inicio=2000)

    # Permite que o tipo venha do event, padrão 'movie' se não vier
    tipo = event.get("tipo", "movie")

    arquivos_discover = processar_discover(api_key, bucket, periodos, tipo)
    arquivos_generos = processar_generos(api_key, bucket, tipo)

    arquivos_totais = arquivos_discover + arquivos_generos
    glue = chamar_glue_etl(glue_job) if arquivos_totais else None

    return {
        "statusCode": 200,
        "body": {
            "tipo": tipo,
            "arquivos_discover": arquivos_discover,
            "arquivos_generos": arquivos_generos,
            "glue": glue
        }
    }


if __name__ == "__main__":
    print(lambda_handler({}, None))