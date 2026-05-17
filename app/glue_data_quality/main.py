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


def main(argv=None):
    argv = argv or sys.argv
    args = parse_args(argv)

    database = args["DATABASE"]
    table = args["TABLE"]
    partition_values = args.get("PARTITION_VALUES")
    s3_bucket_dq = args["S3_BUCKET_DATA_QUALITY"]

    push_down_predicate = build_push_down_predicate(partition_values)

    glue_context = GlueContext(SparkContext.getOrCreate())
    datasource = read_catalog_table(glue_context, database, table, push_down_predicate=push_down_predicate)
    ruleset = build_ruleset(table)

    dq_results = run_data_quality(datasource=datasource, ruleset=ruleset)

    df_dq_results = dq_results.toDF()
    df_dq_results.show(truncate=False)
    table_root_path = write_results(df_dq_results, s3_bucket_dq, table, partition=partition_values)
    register_partition(database, table, table_root_path)


if __name__ == "__main__":
    main()