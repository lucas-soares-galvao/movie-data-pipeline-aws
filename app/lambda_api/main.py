import os
from app.lambda_api.src.utils import (
        obter_tmdb_api_key,
        gerar_periodos_mensais,
        buscar_filmes_por_periodo,
        salvar_json_no_s3,
        chamar_glue_etl
    )


def lambda_handler(event, context):
    secret_arn = os.getenv("TMDB_SECRET_ARN")
    bucket = os.getenv("S3_BUCKET_SOR")
    glue_job = os.getenv("GLUE_ETL_JOB_NAME")

    api_key = obter_tmdb_api_key(secret_arn)

    # Começa no ano desejado
    periodos = gerar_periodos_mensais(ano_inicio=2000)

    arquivos_salvos = []

    for periodo in periodos:
        filmes = buscar_filmes_por_periodo(api_key, periodo)

        ano = periodo["data_inicio"][:4]
        mes = periodo["data_inicio"][5:7]

        key = f"tmdb/year={ano}/month={mes}/movies_{ano}_{mes}.json"

        salvar_json_no_s3(bucket, key, filmes)
        arquivos_salvos.append(key)

    glue = chamar_glue_etl(glue_job)

    return {
        "statusCode": 200,
        "body": {
            "meses_processados": len(arquivos_salvos),
            "arquivos": arquivos_salvos,
            "glue": glue
        }
    }


if __name__ == "__main__":
    print(lambda_handler({}, None))