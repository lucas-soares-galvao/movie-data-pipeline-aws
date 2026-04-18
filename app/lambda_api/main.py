"""Ponto de entrada da Lambda de exemplo."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from src.utils import chamar_glue_etl_e_data_quality, processar_numero, upload_arquivo_para_s3


def lambda_handler(event, context):
    """Handler simples para execucao da Lambda."""
    numero = event.get("numero", 10)
    mensagem = processar_numero(numero)
    glue_execucao = chamar_glue_etl_e_data_quality(
        etl_job_name=event.get("glue_etl_job_name"),
        data_quality_job_name=event.get("glue_data_quality_job_name"),
    )
    
    # Upload do arquivo teste.txt para o bucket SOR
    test_file_path = os.path.join(os.path.dirname(__file__), "teste.txt")
    s3_bucket_sor = os.getenv("S3_BUCKET_SOR")
    upload_result = None
    
    if s3_bucket_sor and os.path.exists(test_file_path):
        upload_result = upload_arquivo_para_s3(
            bucket_name=s3_bucket_sor,
            file_path=test_file_path,
            s3_key="teste.txt"
        )

    return {
        "statusCode": 200,
        "body": {
            "mensagem": mensagem,
            "numero": numero,
            "glue_execucao": glue_execucao,
            "s3_upload": upload_result,
        },
    }

def main():
    # Exemplo simples de execucao local do modulo.
    resultado = processar_numero(10)
    print(resultado)

if __name__ == "__main__":
    main()