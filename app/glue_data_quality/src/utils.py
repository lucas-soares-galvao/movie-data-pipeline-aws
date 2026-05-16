try:
    from awsglue.utils import getResolvedOptions
except ModuleNotFoundError:
    getResolvedOptions = None

try:
    from awsgluedq.transforms import EvaluateDataQuality
except ModuleNotFoundError:
    EvaluateDataQuality = None

try:
    import awswrangler as wr
except ModuleNotFoundError:
    wr = None

try:
    from pyspark.sql.functions import lit
except ModuleNotFoundError:
    lit = None

try:
    from app.glue_data_quality.src.rulesets_dq import rulesets_dq
except ModuleNotFoundError:
    from src.rulesets_dq import rulesets_dq


def parse_args(argv):
    if getResolvedOptions is None:
        raise ModuleNotFoundError("awsglue.utils is required to parse Glue job arguments")

    required_args = ["DATABASE", "TABLE", "S3_BUCKET_DATA_QUALITY"]
    optional_args = [name for name in ["PARTITIONS"] if f"--{name}" in argv]
    return getResolvedOptions(argv, required_args + optional_args)


def get_partition_columns(partitions):
    return partitions.split(",") if partitions else []


def build_ruleset(table_name):
    return rules_list_to_dqdl(rulesets_dq.get(table_name, []))


def read_catalog_table(glue_context, database, table):
    return glue_context.create_dynamic_frame.from_catalog(
        database=database,
        table_name=table,
    )


def run_data_quality(datasource, ruleset, database, table, partition_columns):
    if EvaluateDataQuality is None:
        raise ModuleNotFoundError("awsgluedq.transforms is required to run data quality")

    return EvaluateDataQuality.apply(
        frame=datasource,
        ruleset=ruleset,
        publishing_options={
            "dataQualityEvaluationContext": "meu_contexto",
            "enableDataQualityCloudWatchMetrics": True,
            "enableDataQualityResultsPublishing": True,
        },
        job_name="GlueDataQualityJob",
        database=database,
        table=table,
        partition_columns=partition_columns,
    )


def write_results(
    df_dq_results,
    s3_bucket_dq,
    source_table,
    database=None,
    dq_table="tb_data_quality_tmdb",
):
    if lit is None:
        raise ModuleNotFoundError("pyspark is required to write data quality results")

    table_root_path = f"s3://{s3_bucket_dq}/tmdb/{dq_table}/"
    df_with_source = df_dq_results.withColumn("source_table", lit(source_table))
    df_with_source.write.mode("append").partitionBy("source_table").parquet(
        table_root_path
    )

    # When available, register partition in Glue Catalog for immediate queryability.
    if wr is not None and database:
        partition_prefix = f"source_table={source_table}/"
        partition_path = f"{table_root_path}{partition_prefix}"
        wr.catalog.add_parquet_partitions(
            database=database,
            table=dq_table,
            partitions_values={partition_prefix: partition_path},
        )


def rules_list_to_dqdl(rules_list):
    """
    Converte uma lista de regras em string DQDL para o Glue Data Quality.
    Exemplo:
        ["IsComplete 'id'", "RowCount > 0"]
    vira:
        Rules = [
            IsComplete 'id',
            RowCount > 0
        ]
    """
    if not rules_list:
        return "Rules = [\n    RowCount > 0\n]"
    rules = ",\n    ".join(rules_list)
    return f"Rules = [\n    {rules}\n]"
