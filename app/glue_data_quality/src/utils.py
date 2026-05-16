import awswrangler as wr
from awsglue.utils import getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.sql.functions import lit

from .rulesets_dq import rulesets_dq


def parse_args(argv):
    required_args = ["DATABASE", "TABLE", "S3_BUCKET_DATA_QUALITY"]
    optional_args = [name for name in ["PARTITIONS"] if f"--{name}" in argv]
    return getResolvedOptions(argv, required_args + optional_args)


def get_partition_columns(partitions):
    return partitions.split(",") if partitions else []


def rules_list_to_dqdl(rules_list):
    if not rules_list:
        return "Rules = [\n    RowCount > 0\n]"
    rules = ",\n    ".join(rules_list)
    return f"Rules = [\n    {rules}\n]"


def build_ruleset(table_name):
    return rules_list_to_dqdl(rulesets_dq.get(table_name, []))


def read_catalog_table(glue_context, database, table):
    return glue_context.create_dynamic_frame.from_catalog(
        database=database,
        table_name=table,
    )


def run_data_quality(datasource, ruleset, database, table, partition_columns):
    return EvaluateDataQuality.apply(
        frame=datasource,
        ruleset=ruleset,
        publishing_options={
            "dataQualityEvaluationContext": "meu_contexto",
            "enableDataQualityCloudWatchMetrics": True,
            "enableDataQualityResultsPublishing": True,
        },
        database=database,
        table=table,
        partition_columns=partition_columns,
    )


def write_results(df_dq_results, s3_bucket_dq, source_table, dq_table="tb_data_quality_tmdb"):
    table_root_path = f"s3://{s3_bucket_dq}/tmdb/{dq_table}/"
    df_with_source = df_dq_results.withColumn("source_table", lit(source_table))
    df_with_source.write.mode("append").partitionBy("source_table").parquet(table_root_path)
    return table_root_path


def register_partition(database, source_table, table_root_path, dq_table="tb_data_quality_tmdb"):
    partition_prefix = f"source_table={source_table}/"
    wr.catalog.add_parquet_partitions(
        database=database,
        table=dq_table,
        partitions_values={partition_prefix: f"{table_root_path}{partition_prefix}"},
    )



