"""
Glue Data Quality — avalia regras DQDL (nulos, unicidade, ranges) contra tabelas do SOT.
Requer Spark/GlueContext porque o motor de DQ do Glue não está disponível em PythonShell.
"""

from awsglue.context import GlueContext
from pyspark.context import SparkContext
from shared_utils.glue_helpers import configure_glue_logging
from src.utils import (
    evaluate_data_quality,
    get_parameters_glue,
    get_ruleset,
    notify_failed_outcomes,
    read_table_from_catalog,
    write_results_to_s3,
)

logger = configure_glue_logging()


def main() -> None:
    """
    Executa o pipeline completo de avaliação de qualidade de dados.

    Fluxo: argumentos → contextos Spark → lê dados → avalia regras → salva resultados → notifica.
    """

    # SparkContext: motor de processamento distribuído — necessário porque o Glue DQ
    # roda sobre Spark, não sobre Python puro. GlueContext: wrapper da AWS sobre o
    # SparkContext que adiciona métodos para ler/escrever no Glue Catalog.
    sc = SparkContext.getOrCreate()
    glue_context = GlueContext(sc)

    args = get_parameters_glue()
    table_name               = args["TABLE_NAME"]
    database                 = args["DATABASE"]
    database_results         = args["DATABASE_RESULTS"]
    s3_bucket_data_quality   = args["S3_BUCKET_DATA_QUALITY"]
    environment              = args["ENVIRONMENT"]
    sns_topic_arn_dq_metrics = args["SNS_TOPIC_ARN_DQ_METRICS"]
    output_table             = args["OUTPUT_TABLE"]
    # YEAR pode ser None (tabela sem partição), um único ano ("2025") ou uma lista
    # separada por vírgula ("2020,2021,2023") — o modo changes do glue_details agrupa
    # todos os anos afetados num único disparo para pagar o overhead de startup do
    # Spark uma vez só, em vez de um job run por ano.
    year_arg = args.get("YEAR")
    years: list[str | None] = year_arg.split(",") if year_arg else [None]

    logger.info(
        f"Iniciando Data Quality | tabela: '{table_name}' | banco: '{database}' | anos: {years}"
    )

    ruleset = get_ruleset(table_name, environment)

    for year in years:
        # Para tabelas com partição por ano, push_down_predicate lê só o ano atual.
        dynamic_frame = read_table_from_catalog(glue_context, database, table_name, year)

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

    logger.info("Job Glue Data Quality finalizado com sucesso!")


if __name__ == "__main__":
    main()
