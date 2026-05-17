import awswrangler as wr
from awsglue.utils import getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.sql.functions import coalesce, current_timestamp, lit

from .rulesets_dq import rulesets_dq


def parse_args(argv):
    required_args = ["DATABASE", "TABLE", "S3_BUCKET_DATA_QUALITY"]
    optional_args = [name for name in ["PARTITIONS", "PARTITION_VALUES"] if f"--{name}" in argv]
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


def write_results(df_dq_results, s3_bucket_dq, source_table, partition=None, dq_table="tb_data_quality_tmdb"):
    table_root_path = f"s3://{s3_bucket_dq}/tmdb/{dq_table}/"
    df_enriched = (
        df_dq_results
        .withColumn("source_table", lit(source_table))
        .withColumn("partition", coalesce(lit(partition), lit("")))
        .withColumn("datetime_process", current_timestamp())
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



