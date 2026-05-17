import awswrangler as wr
from awsglue.utils import getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.sql.functions import coalesce, col, current_timestamp, from_utc_timestamp, lit, when

from .rulesets_dq import rulesets_dq


def parse_args(argv):
    required_args = ["DATABASE", "TABLE", "S3_BUCKET_DATA_QUALITY"]
    optional_args = ["PARTITION_VALUES"] if "--PARTITION_VALUES" in argv else []
    return getResolvedOptions(argv, required_args + optional_args)


def rules_list_to_dqdl(rules_list):
    if not rules_list:
        return "Rules = [\n    RowCount > 0\n]"
    rules = ",\n    ".join(rules_list)
    return f"Rules = [\n    {rules}\n]"


def build_ruleset(table_name):
    return rules_list_to_dqdl(rulesets_dq.get(table_name, []))


def build_push_down_predicate(partition_values_str):
    """Convert 'year=2025' format to a Spark SQL predicate for Glue catalog filtering."""
    if not partition_values_str:
        return None
    parts = partition_values_str.split("=", 1)
    if len(parts) != 2:
        return None
    col, val = parts[0].strip(), parts[1].strip()
    return f"{col} = '{val}'"


def read_catalog_table(glue_context, database, table, push_down_predicate=None):
    kwargs = {}
    if push_down_predicate:
        kwargs["push_down_predicate"] = push_down_predicate
    return glue_context.create_dynamic_frame.from_catalog(
        database=database,
        table_name=table,
        **kwargs
    )


def run_data_quality(datasource, ruleset):
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
    df_dq_results,
    s3_bucket_dq,
    source_table,
    partition=None,
    source_database=None,
    dq_table="tb_data_quality_tmdb"
):
    table_root_path = f"s3://{s3_bucket_dq}/tmdb/{dq_table}/"
    # Keep the persisted schema minimal: remove raw metric payloads from Glue DQ output.
    df_base = df_dq_results.drop("evaluated_metrics", "EvaluatedMetrics")

    columns = set(getattr(df_base, "columns", []))
    outcome_col = "Outcome" if "Outcome" in columns else ("outcome" if "outcome" in columns else None)
    failure_reason_col = (
        "FailureReason"
        if "FailureReason" in columns
        else ("failure_reason" if "failure_reason" in columns else None)
    )

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


def register_partition(database, source_table, table_root_path, dq_table="tb_data_quality_tmdb"):
    partition_prefix = f"source_table={source_table}/"
    wr.catalog.add_parquet_partitions(
        database=database,
        table=dq_table,
        partitions_values={f"{table_root_path}{partition_prefix}": [source_table]},
    )



