"""Ponto de entrada da aplicacao usada no job de Glue."""

import sys

from app.glue_etl.src.utils import chamar_glue_data_quality, eh_par, processar_numero


def obter_arg_data_quality_job_name(argv):
    """Le o nome do job de Data Quality passado via argumentos do Glue."""
    for index, arg in enumerate(argv):
        if arg == "--GLUE_DATA_QUALITY_JOB_NAME" and index + 1 < len(argv):
            return argv[index + 1]
    return None


def main():
    # Exemplo simples de execucao local do modulo.
    resultado = processar_numero(10)
    print(resultado)

    # Etapa final: dispara o job de Data Quality apos o ETL.
    data_quality_job_name = obter_arg_data_quality_job_name(sys.argv)
    execucao_data_quality = chamar_glue_data_quality(
        data_quality_job_name=data_quality_job_name,
    )
    print(execucao_data_quality)

if __name__ == "__main__":
    main()