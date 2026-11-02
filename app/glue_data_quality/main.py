"""
Glue Data Quality — avalia regras DQDL (nulos, unicidade, ranges) contra tabelas do SOT.
Requer Spark/GlueContext porque o motor de DQ do Glue não está disponível em PythonShell.
"""

from typing import Any

from awsglue.context import GlueContext
from pyspark.context import SparkContext
from shared_utils.glue_helpers import configure_glue_logging
from src.utils import (
    evaluate_data_quality,
    get_parameters_glue,
    get_ruleset,
    has_data,
    notify_failed_outcomes,
    read_table_from_catalog,
    write_results_to_s3,
)

logger = configure_glue_logging()


def _evaluate_table(
    glue_context: Any,
    table_name: str,
    years: list[str | None],
    database: str,
    database_results: str,
    s3_bucket_data_quality: str,
    environment: str,
    sns_topic_arn_dq_metrics: str,
    output_table: str,
) -> None:
    """
    Avalia o DQ de uma tabela em todos os anos pedidos, dentro do SparkContext já aberto.

    Args:
        glue_context:             GlueContext compartilhado por todas as tabelas do run.
        table_name:               Nome da tabela no Glue Catalog.
        years:                    Anos a avaliar (`[None]` para tabela sem partição por ano).
        database:                 Banco da tabela avaliada.
        database_results:         Banco da tabela de resultados do DQ.
        s3_bucket_data_quality:   Bucket onde os resultados são gravados.
        environment:              Ambiente de execução (dev, prod).
        sns_topic_arn_dq_metrics: Tópico SNS notificado quando alguma regra falha.
        output_table:             Tabela de resultados do DQ.
    """
    ruleset = get_ruleset(table_name, environment)

    for year in years:
        # Para tabelas com partição por ano, push_down_predicate lê só o ano atual.
        dynamic_frame = read_table_from_catalog(glue_context, database, table_name, year)

        # Partição inexistente ou vazia (ex.: watch_providers nunca escreveu esse year
        # porque nenhum id do grupo tinha provedores BR) faz dynamic_frame.toDF() vir
        # sem schema — pula esse year com warning em vez de derrubar o job inteiro
        # (e, num run multi-year, os demais years junto com ele).
        if not has_data(dynamic_frame):
            logger.warning(
                f"Nenhum dado encontrado para '{table_name}'"
                + (f" year={year}" if year is not None else "")
                + " — partição inexistente ou vazia. Pulando avaliação DQ."
            )
            continue

        df_results = evaluate_data_quality(
            glue_context, dynamic_frame, ruleset, table_name, database, year
        )

        write_results_to_s3(
            df_results,
            s3_bucket_data_quality,
            table_name,
            database_results,
            output_table,
            year,
        )

        notify_failed_outcomes(df_results, table_name, sns_topic_arn_dq_metrics, environment, year)


def main() -> None:
    """
    Executa o pipeline completo de avaliação de qualidade de dados.

    Fluxo: argumentos → contextos Spark → para cada tabela e cada ano: lê dados → avalia regras →
    salva resultados → notifica.

    Raises:
        ValueError:   Se TABLE_NAME não trouxer nenhuma tabela.
        RuntimeError: Se a avaliação de alguma tabela falhar — só depois de tentar todas as demais.
    """

    # SparkContext: motor de processamento distribuído — necessário porque o Glue DQ
    # roda sobre Spark, não sobre Python puro. GlueContext: wrapper da AWS sobre o
    # SparkContext que adiciona métodos para ler/escrever no Glue Catalog.
    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)

    args = get_parameters_glue()
    database                 = args["DATABASE"]
    database_results         = args["DATABASE_RESULTS"]
    s3_bucket_data_quality   = args["S3_BUCKET_DATA_QUALITY"]
    environment              = args["ENVIRONMENT"]
    sns_topic_arn_dq_metrics = args["SNS_TOPIC_ARN_DQ_METRICS"]
    output_table             = args["OUTPUT_TABLE"]
    # TABLE_NAME pode ser uma tabela ("tb_tmdb_details_movie_prod") ou uma lista separada por
    # vírgula ("tb_tmdb_details_movie_prod,tb_tmdb_watch_providers_movie_prod") — o glue_details
    # agrupa as tabelas que grava no mesmo ciclo (mesmo banco, mesmos anos) num único disparo
    # para pagar o overhead de startup do Spark uma vez só, em vez de um job run por tabela.
    table_names = [name.strip() for name in args["TABLE_NAME"].split(",") if name.strip()]
    if not table_names:
        raise ValueError("TABLE_NAME não trouxe nenhuma tabela para avaliar.")
    # YEAR pode ser None (tabela sem partição), um único ano ("2025") ou uma lista
    # separada por vírgula ("2020,2021,2023") — o modo changes do glue_details agrupa
    # todos os anos afetados num único disparo para pagar o overhead de startup do
    # Spark uma vez só, em vez de um job run por ano. A lista de anos vale para todas as tabelas.
    year_arg = args.get("YEAR")
    years: list[str | None] = year_arg.split(",") if year_arg else [None]

    logger.info(
        f"Iniciando Data Quality | tabelas: {table_names} | banco: '{database}' | anos: {years}"
    )

    failed_tables: list[str] = []
    for table_name in table_names:
        # Isola cada tabela: uma falha (ex.: tabela sem regras, erro do motor de DQ) não pode
        # impedir a avaliação das demais do mesmo run. O job ainda termina em FAILED no final.
        try:
            _evaluate_table(
                glue_context,
                table_name,
                years,
                database,
                database_results,
                s3_bucket_data_quality,
                environment,
                sns_topic_arn_dq_metrics,
                output_table,
            )
        except Exception:
            logger.exception(f"Falha ao avaliar o Data Quality de '{table_name}'.")
            failed_tables.append(table_name)

    if failed_tables:
        raise RuntimeError(f"Data Quality falhou para: {', '.join(failed_tables)}")

    logger.info("Job Glue Data Quality finalizado com sucesso!")


if __name__ == "__main__":
    main()
