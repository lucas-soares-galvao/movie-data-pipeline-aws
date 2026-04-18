"""Ponto de entrada da aplicacao usada no job de Glue."""

import os
import sys

from app.glue_etl.src.utils import (
    chamar_glue_data_quality,
    eh_par,
    processar_numero,
    ler_arquivo_do_s3,
    escrever_arquivo_no_s3,
    processar_arquivo_etl,
)


def obter_arg_data_quality_job_name(argv):
    """Le o nome do job de Data Quality passado via argumentos do Glue."""
    for index, arg in enumerate(argv):
        if arg == "--GLUE_DATA_QUALITY_JOB_NAME" and index + 1 < len(argv):
            return argv[index + 1]
    return None


def processar_arquivo_sor_para_sot(s3_bucket_sor, s3_bucket_sot, s3_key_entrada, s3_key_saida):
    """Lê arquivo do bucket SOR, processa e escreve no bucket SOT."""
    # Lê arquivo do SOR
    conteudo_entrada = ler_arquivo_do_s3(
        bucket_name=s3_bucket_sor,
        s3_key=s3_key_entrada
    )
    
    # Processa o conteúdo
    conteudo_processado = processar_arquivo_etl(conteudo_entrada)
    
    # Escreve no SOT
    resultado = escrever_arquivo_no_s3(
        bucket_name=s3_bucket_sot,
        s3_key=s3_key_saida,
        conteudo=conteudo_processado
    )
    
    return resultado


def main():
    # Exemplo simples de execucao local do modulo.
    resultado = processar_numero(10)
    print(resultado)
    
    # Configuracoes dos buckets S3
    s3_bucket_sor = os.getenv("S3_BUCKET_SOR", "lsg-sa-east-1-bucket-sor")
    s3_bucket_sot = os.getenv("S3_BUCKET_SOT", "lsg-sa-east-1-bucket-sot")
    
    # Processa arquivo do SOR e escreve no SOT
    try:
        resultado_etl = processar_arquivo_sor_para_sot(
            s3_bucket_sor=s3_bucket_sor,
            s3_bucket_sot=s3_bucket_sot,
            s3_key_entrada="teste.txt",
            s3_key_saida="teste_processado.txt"
        )
        print(f"ETL concluído com sucesso: {resultado_etl}")
    except Exception as e:
        print(f"Erro ao processar arquivo ETL: {str(e)}")
        raise

    # Etapa final: dispara o job de Data Quality apos o ETL.
    data_quality_job_name = obter_arg_data_quality_job_name(sys.argv)
    execucao_data_quality = chamar_glue_data_quality(
        data_quality_job_name=data_quality_job_name,
    )
    print(execucao_data_quality)

if __name__ == "__main__":
    main()