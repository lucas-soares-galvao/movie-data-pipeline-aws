"""
utils.py — Funções auxiliares do job Glue Data Quality.

Responsabilidades:
  - Ler os argumentos do job (TABLE_NAME, DATABASE, S3_BUCKET_DATA_QUALITY, ENVIRONMENT)
  - Buscar o ruleset (conjunto de regras DQDL) da tabela em rulesets_dq.py
  - Ler a tabela do Glue Catalog como DynamicFrame
  - Avaliar a qualidade dos dados com EvaluateDataQuality
  - Gravar o resultado da avaliação no S3 como Parquet, particionado por source_table
"""

import logging
import sys
from typing import Any, Dict

from awsglue.context import GlueContext
from awsglue.utils import getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.sql.functions import current_timestamp, lit

from src.rulesets_dq import rulesets_dq

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Leitura de argumentos do job
# ---------------------------------------------------------------------------

def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios e opcionais passados ao job Glue pelo Glue ETL.

    Argumentos obrigatórios: TABLE_NAME, DATABASE, S3_BUCKET_DATA_QUALITY, ENVIRONMENT.
    Argumento opcional:      YEAR (presente apenas para tabelas de discover).

    Returns:
        Dicionário com todos os argumentos resolvidos.
    """
    required_args = [
        "TABLE_NAME",
        "DATABASE",
        "S3_BUCKET_DATA_QUALITY",
        "ENVIRONMENT",
    ]
    args = getResolvedOptions(sys.argv, required_args)

    # YEAR é opcional: o Glue ETL passa --YEAR apenas para runs de discover
    try:
        args.update(getResolvedOptions(sys.argv, ["YEAR"]))
    except Exception:
        pass

    return args


# ---------------------------------------------------------------------------
# Ruleset (conjunto de regras DQDL)
# ---------------------------------------------------------------------------

def get_ruleset(table_name: str) -> str:
    """
    Busca as regras de qualidade definidas em rulesets_dq.py para a tabela e
    monta a string no formato DQDL exigida pelo Glue Data Quality.

    Formato DQDL:
      Rules = [
        IsComplete "id",
        IsUnique "id",
        RowCount > 0
      ]

    Args:
        table_name: Nome da tabela no Glue Catalog.

    Returns:
        String com as regras no formato DQDL.

    Raises:
        KeyError: Se não houver regras definidas para a tabela.
    """
    rules = rulesets_dq.get(table_name)
    if rules is None:
        raise KeyError(
            f"Nenhuma regra de DQ definida para a tabela '{table_name}'. "
            f"Adicione as regras em rulesets_dq.py."
        )

    # Junta as regras separadas por vírgula no formato que o Glue entende
    ruleset = "Rules = [\n  " + ",\n  ".join(rules) + "\n]"
    logger.info(f"Ruleset para '{table_name}':\n{ruleset}")
    return ruleset


# ---------------------------------------------------------------------------
# Leitura da tabela no Glue Catalog
# ---------------------------------------------------------------------------

def read_table_from_catalog(glue_context: GlueContext, database: str, table_name: str):
    """
    Lê uma tabela registrada no Glue Catalog e a retorna como DynamicFrame.

    O DynamicFrame é o formato padrão do AWS Glue para representar dados
    distribuídos (semelhante ao DataFrame do Spark, mas com suporte extra
    a esquemas flexíveis e tipos aninhados).

    Args:
        glue_context: Contexto do Glue criado no main.py.
        database:     Nome do banco de dados no Glue Catalog.
        table_name:   Nome da tabela a ser lida.

    Returns:
        DynamicFrame com os dados da tabela.
    """
    logger.info(f"Lendo tabela '{database}.{table_name}' do Glue Catalog...")
    return glue_context.create_dynamic_frame.from_catalog(
        database=database,
        table_name=table_name,
    )


# ---------------------------------------------------------------------------
# Avaliação da qualidade dos dados
# ---------------------------------------------------------------------------

def evaluate_data_quality(
    glue_context: GlueContext,
    dynamic_frame,
    ruleset: str,
    table_name: str,
):
    """
    Executa a avaliação de qualidade dos dados com o EvaluateDataQuality do Glue.

    O resultado é um DynamicFrame com uma linha por regra avaliada, contendo:
      - Rule        : expressão da regra (ex.: 'IsComplete "id"')
      - Outcome     : "Passed" ou "Failed"
      - FailureReason : motivo da falha (vazio se passou)
      - EvaluatedMetrics : métricas calculadas para a regra

    Após a avaliação, duas colunas são adicionadas ao resultado:
      - source_table : nome da tabela avaliada (usada como partição no S3)
      - evaluated_at : timestamp do momento da avaliação

    Args:
        glue_context:  Contexto do Glue.
        dynamic_frame: DynamicFrame com os dados da tabela lida do Catalog.
        ruleset:       String de regras no formato DQDL.
        table_name:    Nome da tabela avaliada.

    Returns:
        Spark DataFrame com os resultados da avaliação.
    """
    logger.info(f"Avaliando qualidade de dados da tabela '{table_name}'...")

    # Executa as regras sobre o DynamicFrame e retorna outro DynamicFrame com os resultados
    dq_results = EvaluateDataQuality.apply(
        frame=dynamic_frame,
        ruleset=ruleset,
        publishing_options={
            # Nome do contexto que aparece nos resultados publicados no Glue Studio
            "dataQualityEvaluationContext": table_name,
            # Publica métricas no CloudWatch para monitoramento
            "enableDataQualityCloudWatchMetrics": True,
            # Publica os resultados no painel de Data Quality do Glue Studio
            "enableDataQualityResultsPublishing": True,
        },
    )

    # Converte DynamicFrame → Spark DataFrame para poder adicionar colunas extras
    df = dq_results.toDF()

    # Adiciona colunas de contexto para rastreabilidade nos relatórios
    df = df.withColumn("source_table", lit(table_name))   # partição no S3
    df = df.withColumn("evaluated_at", current_timestamp())  # horário da avaliação

    logger.info(f"Avaliação concluída. Regras avaliadas: {df.count()}")
    return df


# ---------------------------------------------------------------------------
# Gravação dos resultados no S3
# ---------------------------------------------------------------------------

def write_results_to_s3(
    df,
    s3_bucket_data_quality: str,
    table_name: str,
) -> None:
    """
    Grava o DataFrame com os resultados do Data Quality no S3 como Parquet,
    particionado pela coluna source_table.

    Caminho de escrita:
      s3://<bucket>/tmdb/tb_data_quality_tmdb/source_table=<table_name>/

    O modo "append" garante que resultados de avaliações anteriores de outras
    tabelas não sejam apagados — cada tabela fica em sua própria partição.

    Args:
        df:                     Spark DataFrame com os resultados da avaliação.
        s3_bucket_data_quality: Nome do bucket de Data Quality.
        table_name:             Nome da tabela avaliada (informativo para o log).
    """
    output_table = "tb_data_quality_tmdb"
    s3_path = f"s3://{s3_bucket_data_quality}/tmdb/{output_table}/"

    logger.info(
        f"Gravando resultados em {s3_path} | partição: source_table='{table_name}'"
    )

    (
        df.write
        .mode("append")                # append: preserva resultados de outras tabelas
        .partitionBy("source_table")   # cria subpastas source_table=<nome_da_tabela>
        .parquet(s3_path)
    )

    logger.info(f"Resultados de '{table_name}' gravados com sucesso!")
