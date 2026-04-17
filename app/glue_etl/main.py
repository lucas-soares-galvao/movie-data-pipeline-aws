"""Ponto de entrada da aplicacao usada no job de Glue."""

from app.glue_etl.src.utils import chamar_glue_data_quality, eh_par, processar_numero


def main():
    # Exemplo simples de execucao local do modulo.
    resultado = processar_numero(10)
    print(resultado)

    # Etapa final: dispara o job de Data Quality apos o ETL.
    execucao_data_quality = chamar_glue_data_quality()
    print(execucao_data_quality)

if __name__ == "__main__":
    main()