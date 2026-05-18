"""Raciocinio: implementa parsing de args, leitura do catalogo, avaliacao DQ e escrita padronizada de saida."""

from typing import Any

import awswrangler as wr
from awsglue.utils import getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.sql.functions import coalesce, col, current_timestamp, from_utc_timestamp, lit, when

from .rulesets_dq import rulesets_dq


def _resolve_optional_args(argv: list[str], optional_args: list[str]) -> dict[str, str]:
    """Extrai argumentos opcionais do argv sem quebrar quando nao forem informados."""
    resolved: dict[str, str] = {}
    for arg in optional_args:
        option = f"--{arg}"
        if option in argv:
            index = argv.index(option)
            if index + 1 < len(argv):
                resolved[arg] = argv[index + 1]
    return resolved


def parse_args(argv: list[str]) -> dict[str, str]:
    """Resolve os parametros obrigatorios do job e injeta o opcional de particao."""
    required_args = ["DATABASE", "TABLE", "S3_BUCKET_DATA_QUALITY"]
    args = getResolvedOptions(argv, required_args)
    args.update(_resolve_optional_args(argv, ["PARTITION_VALUES"]))
    return args


def rules_list_to_dqdl(rules_list: list[str]) -> str:
    """Converte a lista de regras em DQDL, com fallback minimo para evitar job sem regra."""
    if not rules_list:
        return "Rules = [\n    RowCount > 0\n]"
    rules = ",\n    ".join(rules_list)
    return f"Rules = [\n    {rules}\n]"


def build_ruleset(table_name: str) -> str:
    """Seleciona o ruleset por tabela e mantém a validacao declarativa em arquivo dedicado."""
    return rules_list_to_dqdl(rulesets_dq.get(table_name, []))


def build_push_down_predicate(partition_values_str: str | None) -> str | None:
    """Converte o formato 'year=2025' para um predicado Spark SQL de filtro no Catalog."""
    if not partition_values_str:
        return None
    parts = partition_values_str.split("=", 1)
    if len(parts) != 2:
        return None
    col, val = parts[0].strip(), parts[1].strip()
    return f"{col} = '{val}'"


def read_catalog_table(
    glue_context: Any,
    database: str,
    table: str,
    push_down_predicate: str | None = None,
) -> Any:
    """Le a tabela do Glue Catalog com filtro opcional de particao na origem."""
    kwargs = {}
    if push_down_predicate:
        kwargs["push_down_predicate"] = push_down_predicate
    return glue_context.create_dynamic_frame.from_catalog(
        database=database,
        table_name=table,
        **kwargs
    )


def run_data_quality(datasource: Any, ruleset: str) -> Any:
    """Executa a avaliacao de qualidade e publica metricas/resultados no ecossistema Glue."""
    return EvaluateDataQuality.apply(
        frame=datasource,
        ruleset=ruleset,
        publishing_options={
            "dataQualityEvaluationContext": "meu_contexto",
            "enableDataQualityCloudWatchMetrics": True,
            "enableDataQualityResultsPublishing": True,
        },
    )


def write_results(
    df_dq_results: Any,
    s3_bucket_dq: str,
    source_table: str,
    partition: str | None = None,
    source_database: str | None = None,
    dq_table: str = "tb_data_quality_tmdb",
) -> str:
    """Padroniza e grava o resultado de DQ em Parquet para consulta historica e auditoria."""
    table_root_path = f"s3://{s3_bucket_dq}/tmdb/{dq_table}/"
    # Keep the persisted schema minimal: remove raw metric payloads from Glue DQ output.
    df_base = df_dq_results.drop("evaluated_metrics", "EvaluatedMetrics")

    # Compatibiliza diferentes nomes de colunas retornadas pelo Glue DQ.
    columns = set(getattr(df_base, "columns", []))
    outcome_col = "Outcome" if "Outcome" in columns else ("outcome" if "outcome" in columns else None)
    failure_reason_col = (
        "FailureReason"
        if "FailureReason" in columns
        else ("failure_reason" if "failure_reason" in columns else None)
    )

    # Enriquecimento do motivo de falha para evitar registros sem explicacao.
    if outcome_col and failure_reason_col:
        failure_reason_expr = (
            when(
                (col(outcome_col) == "Failed")
                & col(failure_reason_col).isNotNull()
                & (col(failure_reason_col) != ""),
                col(failure_reason_col),
            )
            .when(
                col(outcome_col) == "Failed",
                lit("DQ metric failed without explicit reason"),
            )
            .otherwise(lit(""))
        )
    elif outcome_col:
        failure_reason_expr = when(
            col(outcome_col) == "Failed",
            lit("DQ metric failed without explicit reason"),
        ).otherwise(lit(""))
    else:
        failure_reason_expr = lit("")

    # Adiciona metadados de rastreio para facilitar consumo analitico e observabilidade.
    df_enriched = (
        df_base
        .withColumn("source_table", lit(source_table))
        .withColumn("source_database", coalesce(lit(source_database), lit("")))
        .withColumn("partition", coalesce(lit(partition), lit("")))
        .withColumn("failure_reason", failure_reason_expr)
        .withColumn("datetime_process", from_utc_timestamp(current_timestamp(), "America/Sao_Paulo"))
    )
    df_enriched.write.mode("append").partitionBy("source_table").parquet(table_root_path)
    return table_root_path


def register_partition(
    database: str,
    source_table: str,
    table_root_path: str,
    dq_table: str = "tb_data_quality_tmdb",
) -> None:
    """Registra no Catalog a particao escrita para consulta imediata sem crawler."""
    partition_prefix = f"source_table={source_table}/"
    wr.catalog.add_parquet_partitions(
        database=database,
        table=dq_table,
        partitions_values={f"{table_root_path}{partition_prefix}": [source_table]},
    )
