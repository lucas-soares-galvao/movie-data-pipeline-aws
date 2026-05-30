"""
main.py — Ponto de entrada do job Glue Data Quality.

Este job valida a qualidade dos dados gravados na camada SOT.
Para cada tabela informada, ele:
  1. Lê os dados do bucket SOT (Parquet).
  2. Aplica as regras de qualidade definidas em src/rulesets_dq.py.
  3. Salva os resultados (passou / falhou) como Parquet no bucket de
     Data Quality para posterior consulta via Athena.

Argumentos recebidos (enviados pelo Glue ETL ao acionar este job):
  JOB_NAME             — nome do job (injetado pelo Glue)
  DATABASE             — banco de dados no Glue Catalog
  TABLE_NAME           — nome da tabela a ser validada
  S3_BUCKET_SOT        — bucket onde os dados da tabela estão armazenados
  S3_BUCKET_DATA_QUALITY — bucket onde os resultados serão gravados

  Argumento fixo (default_arguments no Terraform):
  S3_BUCKET_DATA_QUALITY

  Argumento opcional (enviado pelo ETL só para tabelas de discover):
  YEAR                 — filtra apenas a partição do ano informado
"""

import logging
import sys

from awsglue.utils import getResolvedOptions

from src.rulesets_dq import rulesets_dq
from src.utils import evaluate_rules, get_optional_arg, read_table_from_sot, save_dq_results

# ---------------------------------------------------------------------------
# Configuração de log — registros aparecem automaticamente no CloudWatch
# ---------------------------------------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Argumentos sempre presentes em toda execução do job
# ---------------------------------------------------------------------------
args = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "DATABASE",
        "TABLE_NAME",
        "S3_BUCKET_SOT",
        "S3_BUCKET_DATA_QUALITY",
    ],
)

database = args["DATABASE"]
table_name = args["TABLE_NAME"]
s3_bucket_sot = args["S3_BUCKET_SOT"]
s3_bucket_data_quality = args["S3_BUCKET_DATA_QUALITY"]

# Argumento opcional: presente apenas quando a tabela é particionada por ano
year = get_optional_arg("YEAR")

# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------
logger.info("Iniciando validação de qualidade | tabela: %s | ano: %s", table_name, year)

# Passo 1 — Lê os dados da tabela no bucket SOT
df = read_table_from_sot(
    s3_bucket_sot=s3_bucket_sot,
    table_name=table_name,
    year=year,
)

if df.empty:
    logger.warning("Tabela '%s' está vazia. Encerrando sem gerar resultados.", table_name)
else:
    # Passo 2 — Busca as regras definidas para esta tabela
    rules = rulesets_dq.get(table_name, [])

    if not rules:
        logger.warning("Nenhuma regra de qualidade encontrada para '%s'.", table_name)
    else:
        # Passo 3 — Avalia cada regra e coleta os resultados
        results = evaluate_rules(
            df=df,
            rules=rules,
            database=database,
            table_name=table_name,
            year=year,
        )

        # Passo 4 — Salva os resultados no bucket de Data Quality
        save_dq_results(
            results=results,
            s3_bucket_data_quality=s3_bucket_data_quality,
            table_name=table_name,
        )

logger.info("Validação de qualidade finalizada para tabela '%s'!", table_name)
