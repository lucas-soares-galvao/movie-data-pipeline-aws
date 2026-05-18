"""Raciocinio: entrypoint do Glue Data Quality; le dados alvo, aplica regras e persiste resultados para auditoria."""

import sys

from awsglue.context import GlueContext
from pyspark.context import SparkContext
from src.utils import (
    build_push_down_predicate,
    build_ruleset,
    parse_args,
    read_catalog_table,
    register_partition,
    run_data_quality,
    write_results,
)


def main(argv: list[str] | None = None) -> None:
    """Executa validacao de qualidade e persiste resultados enriquecidos no data lake.

    Raciocinio do fluxo:
    1) le somente a particao alvo (quando informada) para reduzir custo de leitura;
    2) aplica ruleset por tabela para manter contrato de qualidade por dominio;
    3) grava resultado padronizado e registra particao para consulta no Catalog.
    """
    argv = argv or sys.argv
    args = parse_args(argv)

    database = args["DATABASE"]
    table = args["TABLE"]
    partition_values = args.get("PARTITION_VALUES")
    s3_bucket_dq = args["S3_BUCKET_DATA_QUALITY"]

    # Filtragem no Catalog antes da leitura reduz processamento quando o job e disparado por ano.
    push_down_predicate = build_push_down_predicate(partition_values)

    glue_context = GlueContext(SparkContext.getOrCreate())
    datasource = read_catalog_table(glue_context, database, table, push_down_predicate=push_down_predicate)
    # O ruleset e resolvido pelo nome da tabela para aplicar regras especificas de negocio.
    ruleset = build_ruleset(table)

    dq_results = run_data_quality(datasource=datasource, ruleset=ruleset)

    df_dq_results = dq_results.toDF()
    df_dq_results.show(truncate=False)
    table_root_path = write_results(
        df_dq_results,
        s3_bucket_dq,
        table,
        partition=partition_values,
        source_database=database
    )
    register_partition(database, table, table_root_path)


if __name__ == "__main__":
    main()
