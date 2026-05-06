from src.rulesets_dq import rulesets_dq
from src.utils import rules_list_to_dqdl
import sys
from awsgluedq.transforms import EvaluateDataQuality
from awsglue.context import GlueContext
from pyspark.context import SparkContext
from awsglue.utils import getResolvedOptions

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session

args = getResolvedOptions(sys.argv, [
    "DATABASE",
    "TABLE",
    "S3_BUCKET_DATA_QUALITY"
])

database = args["DATABASE"]
table = args["TABLE"]
partition_columns = args.get("PARTITIONS")
s3_bucket_dq = args["S3_BUCKET_DATA_QUALITY"]

# Lendo tabela do catálogo
datasource = glueContext.create_dynamic_frame.from_catalog(
    database=database,
    table_name=table
)

# Regras DQDL dinâmicas por tabela usando função utilitária
if table in rulesets_dq:
    ruleset = rules_list_to_dqdl(rulesets_dq[table])
else:
    ruleset = rules_list_to_dqdl([])  # fallback mínimo

# Executa validação
dq_results = EvaluateDataQuality.apply(
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
    partition_columns=partition_columns.split(",") if partition_columns else [],
)

df_dq_results = dq_results.toDF()
df_dq_results.show(truncate=False)

# Escreve resultados em S3
df_dq_results.write.mode("overwrite").parquet(f"s3://{s3_bucket_dq}/tmdb/{table}/")