"""Ponto de entrada da Lambda de exemplo."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from src.utils import chamar_glue_etl_e_data_quality, processar_numero


def lambda_handler(event, context):
    """Handler simples para execucao da Lambda."""
    numero = event.get("numero", 10)
    mensagem = processar_numero(numero)
    glue_execucao = chamar_glue_etl_e_data_quality(
        etl_job_name=event.get("glue_etl_job_name"),
        data_quality_job_name=event.get("glue_data_quality_job_name"),
    )

    return {
        "statusCode": 200,
        "body": {
            "mensagem": mensagem,
            "numero": numero,
            "glue_execucao": glue_execucao,
        },
    }

def main():
    # Exemplo simples de execucao local do modulo.
    resultado = processar_numero(10)
    print(resultado)

if __name__ == "__main__":
    main()