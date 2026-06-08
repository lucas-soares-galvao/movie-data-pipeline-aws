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
from typing import Any, Dict, Optional

import awswrangler as wr
import boto3
from awsglue.context import GlueContext
from awsglue.dynamicframe import DynamicFrame
from awsglue.utils import GlueArgumentError, getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.sql.functions import col, current_timestamp, from_utc_timestamp, lit
from pyspark.sql.types import StringType

from src.rulesets_dq import rulesets_dq

logger = logging.getLogger()


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
        "SNS_TOPIC_ARN",
    ]
    args = getResolvedOptions(sys.argv, required_args)

    # YEAR é opcional: o Glue ETL passa --YEAR apenas para runs de discover
    try:
        args.update(getResolvedOptions(sys.argv, ["YEAR"]))
    except (SystemExit, GlueArgumentError):
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


def read_table_from_catalog(
    glue_context: GlueContext,
    database: str,
    table_name: str,
    year: Optional[str] = None,
):
    """
    Lê uma tabela registrada no Glue Catalog e a retorna como DynamicFrame.

    O DynamicFrame é o formato padrão do AWS Glue para representar dados
    distribuídos (semelhante ao DataFrame do Spark, mas com suporte extra
    a esquemas flexíveis e tipos aninhados).

    Quando `year` é informado (tabelas de discover particionadas por ano), aplica
    um `push_down_predicate` para ler **apenas** a partição recém-escrita. Isso
    evita que o Glue tente acessar arquivos de outras partições que possam ter
    metadados obsoletos no Catalog após re-escritas anteriores.

    Args:
        glue_context: Contexto do Glue criado no main.py.
        database:     Nome do banco de dados no Glue Catalog.
        table_name:   Nome da tabela a ser lida.
        year:         Ano da partição a filtrar. None lê a tabela inteira.

    Returns:
        DynamicFrame com os dados da tabela (ou partição, quando year é fornecido).
    """
    logger.info(f"Lendo tabela '{database}.{table_name}' do Glue Catalog...")
    kwargs: Dict[str, Any] = {
        "database": database,
        "table_name": table_name,
    }
    if year is not None:
        kwargs["push_down_predicate"] = f"year = '{year}'"
        logger.info(f"Aplicando filtro de partição: year = '{year}'")
    return glue_context.create_dynamic_frame.from_catalog(**kwargs)


# ---------------------------------------------------------------------------
# Avaliação da qualidade dos dados
# ---------------------------------------------------------------------------


def evaluate_data_quality(
    glue_context: GlueContext,
    dynamic_frame,
    ruleset: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
):
    """
    Executa a avaliação de qualidade dos dados com o EvaluateDataQuality do Glue.

    O Glue DQ retorna um DynamicFrame com colunas em PascalCase:
      - Rule             : expressão da regra (ex.: 'IsComplete "id"')
      - Outcome          : "Passed" ou "Failed"
      - FailureReason    : motivo da falha (null se passou)
      - EvaluatedMetrics : métricas calculadas para a regra

    As colunas são renomeadas para snake_case (necessário para que o Athena
    consiga ler failure_reason corretamente) e as seguintes colunas de contexto
    são adicionadas:
      - partition        : ano da partição da tabela avaliada (None se não aplicável)
      - datetime_process : timestamp do momento da avaliação
      - source_database  : banco de dados no Glue Catalog
      - source_table     : nome da tabela avaliada (usada como partição no S3)

    Args:
        glue_context:  Contexto do Glue.
        dynamic_frame: DynamicFrame com os dados da tabela lida do Catalog.
        ruleset:       String de regras no formato DQDL.
        table_name:    Nome da tabela avaliada.
        database:      Nome do banco de dados no Glue Catalog.
        year:          Ano da partição. Preenchido apenas para tabelas de discover.

    Returns:
        Spark DataFrame com os resultados da avaliação e colunas de contexto.
    """
    logger.info(f"Avaliando qualidade de dados da tabela '{table_name}'...")

    # Para tabelas de discover (particionadas por ano), filtra o DataFrame pelo ano da partição
    # antes de avaliar. Isso garante que o Glue DQ avalie apenas os dados do ano solicitado,
    # mesmo que o push_down_predicate do Catalog já tenha filtrado a partição no S3.
    if year is not None:
        df_source = dynamic_frame.toDF().filter(col("year") == year)
        dynamic_frame = DynamicFrame.fromDF(df_source, glue_context, "filtered_frame")
        logger.info(f"Filtro aplicado no DataFrame: year = '{year}'")

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

    # Converte DynamicFrame → Spark DataFrame e renomeia colunas PascalCase → snake_case.
    # Sem o rename, o Athena leria "FailureReason" como coluna desconhecida e retornaria null
    # no campo failure_reason do schema, mesmo quando a regra falha.
    df = (
        dq_results.toDF()
        .withColumnRenamed("Rule", "rule")
        .withColumnRenamed("Outcome", "outcome")
        .withColumnRenamed("FailureReason", "failure_reason")
        .withColumnRenamed("EvaluatedMetrics", "evaluated_metrics")
        .drop(
            "EvaluatedRule"
        )  # coluna extra do Glue DQ não mapeada no schema do Catalog
    )

    # EvaluatedMetrics é retornada pelo Glue DQ como map<string, double> — tipo complexo
    # que falha no commit de staging do S3 ao escrever Parquet particionado.
    # O cast para StringType serializa o mapa como string, garantindo compatibilidade.
    df = df.withColumn("evaluated_metrics", col("evaluated_metrics").cast(StringType()))

    # Adiciona colunas de contexto para rastreabilidade e particionamento
    df = df.withColumn(
        "partition", lit(year).cast(StringType())
    )  # ano da partição (None para gêneros/config)
    df = df.withColumn(
        "datetime_process", from_utc_timestamp(current_timestamp(), "America/Sao_Paulo")
    )  # horário em São Paulo
    df = df.withColumn("source_database", lit(database))  # banco de dados avaliado
    df = df.withColumn("source_table", lit(table_name))  # partição no S3

    logger.info(f"Avaliação concluída. Regras avaliadas: {df.count()}")
    return df


# ---------------------------------------------------------------------------
# Gravação dos resultados no S3
# ---------------------------------------------------------------------------


def write_results_to_s3(
    df,
    s3_bucket_data_quality: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> None:
    """
    Grava o DataFrame com os resultados do Data Quality no S3 como Parquet,
    particionado pela coluna source_table, e atualiza o Glue Catalog automaticamente.

    Usa o AWS Wrangler (mesmo padrão do Glue ETL) para registrar as partições
    no Catalog após a escrita, eliminando a necessidade de MSCK REPAIR TABLE no Athena.

    A coluna 'partition' (ano) é mantida como dado normal dentro do Parquet —
    não é usada em partition_cols — para evitar que o Wrangler remova seu valor
    do arquivo e o Athena retorne null ao consultar a tabela.

    Caminho de escrita:
      s3://<bucket>/tmdb/tb_data_quality_tmdb/
        └── source_table=<table_name>/
              └── part-00000.parquet  (contém a coluna partition como dado)

    Args:
        df:                     Spark DataFrame com os resultados da avaliação.
        s3_bucket_data_quality: Nome do bucket de Data Quality.
        table_name:             Nome da tabela avaliada (informativo para o log).
        database:               Nome do banco de dados no Glue Catalog.
        year:                   Ano da partição (informativo; já está na coluna
                                'partition' do DataFrame).
    """
    output_table = "tb_data_quality_tmdb"
    s3_path = f"s3://{s3_bucket_data_quality}/tmdb/{output_table}/"

    logger.info(
        f"Gravando resultados em {s3_path} | source_table='{table_name}' | partition='{year}'"
    )

    wr.s3.to_parquet(
        df=df.toPandas(),
        path=s3_path,
        dataset=True,
        database=database,
        table=output_table,
        partition_cols=["source_table"],
        mode="overwrite_partitions",
    )

    logger.info(f"Resultados de '{table_name}' gravados com sucesso!")


# ---------------------------------------------------------------------------
# Notificação SNS para outcomes Failed
# ---------------------------------------------------------------------------


def notify_failed_outcomes(
    df,
    table_name: str,
    sns_topic_arn: str,
    environment: str,
) -> None:
    """
    Verifica se alguma regra DQ teve outcome "Failed" e publica no SNS.

    O job termina com SUCCEEDED mesmo quando regras falham — essa função
    garante que o time seja notificado sobre falhas de métricas de dados,
    não apenas sobre crashes do job.

    Args:
        df:            Spark DataFrame com os resultados da avaliação (colunas rule, outcome, failure_reason).
        table_name:    Nome da tabela avaliada.
        sns_topic_arn: ARN do tópico SNS para publicar a notificação.
        environment:   Ambiente (dev, prod) para compor o subject do e-mail.
    """
    failed_df = df.filter(col("outcome") == "Failed")
    count = failed_df.count()

    if count == 0:
        logger.info(f"Todas as regras passaram para '{table_name}'.")
        return

    rows = failed_df.select("rule", "failure_reason").collect()
    lines = [
        "[DQ Métrica Falha]",
        f"Ambiente: {environment}",
        f"Tabela: {table_name}",
        f"Regras com falha ({count}):",
    ]
    for row in rows:
        lines.append(f"  • {row['rule']} → {row['failure_reason']}")

    message = "\n".join(lines)
    boto3.client("sns").publish(
        TopicArn=sns_topic_arn,
        Subject=f"[{environment.upper()}] DQ Métrica Falha - {table_name}",
        Message=message,
    )
    logger.warning(f"{count} regra(s) falharam para '{table_name}'. Notificação SNS enviada.")
