"""utils.py — Funções auxiliares do job Glue Data Quality."""

import logging
import sys
from typing import Any, Dict, Optional

import awswrangler as wr
import boto3
from awsglue.context import GlueContext
from awsglue.dynamicframe import DynamicFrame
from awsglue.utils import GlueArgumentError, getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.sql.functions import col, current_timestamp, from_utc_timestamp, lit, when
from pyspark.sql.types import StringType

from src.rulesets_dq import rulesets_dq

logger = logging.getLogger()


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos do job Glue Data Quality.

    Returns:
        Dicionário com todos os argumentos resolvidos.
    """
    required_args = [
        "TABLE_NAME",
        "DATABASE",
        "DATABASE_RESULTS",
        "S3_BUCKET_DATA_QUALITY",
        "ENVIRONMENT",
        "SNS_TOPIC_ARN_DQ_METRICS",
    ]
    args = getResolvedOptions(sys.argv, required_args)

    # YEAR é opcional: passado apenas para tabelas com partição por ano
    # (gênero, configuração e watch_providers_ref não têm partição por ano)
    # Se não existir o argumento YEAR, o try/except evita que o job quebre
    try:
        args.update(getResolvedOptions(sys.argv, ["YEAR"]))
    except (SystemExit, GlueArgumentError):
        pass  # não há YEAR — tabela sem partição por ano; ok continuar

    return args


def get_ruleset(table_name: str, environment: str) -> str:
    """
    Retorna as regras DQDL para a tabela, montadas como string para o Glue Data Quality.

    Converte o nome do Glue Catalog (tb_tmdb_<name>_<env>) para o nome lógico
    usado como chave em rulesets_dq (<name>).

    Args:
        table_name:  Nome da tabela no Glue Catalog (ex: tb_tmdb_genre_movie_prod).
        environment: Ambiente de execução (dev, prod).

    Returns:
        String com as regras no formato DQDL (Rules = [...]).

    Raises:
        KeyError: Se não houver regras definidas para a tabela em rulesets_dq.py.
    """
    logical_name = table_name.removeprefix("tb_tmdb_").removesuffix(f"_{environment}")
    rules = rulesets_dq.get(logical_name)
    if rules is None:
        raise KeyError(
            f"Nenhuma regra de DQ definida para a tabela '{table_name}' "
            f"(chave: '{logical_name}'). Adicione as regras em rulesets_dq.py."
        )

    ruleset = "Rules = [\n  " + ",\n  ".join(rules) + "\n]"
    logger.info(f"Ruleset para '{table_name}':\n{ruleset}")
    return ruleset


def read_table_from_catalog(
    glue_context: GlueContext,
    database: str,
    table_name: str,
    year: Optional[str] = None,
):
    """
    Lê uma tabela do Glue Catalog como DynamicFrame.

    Quando year é informado, aplica push_down_predicate para ler apenas a partição
    recém-escrita e evitar acesso a metadados obsoletos de outras partições.

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
        "table_name": table_name
    }
    if year is not None:
        # push_down_predicate = "filtro de partição empurrado para baixo"
        # Em vez de carregar TODOS os dados e depois filtrar em memória,
        # o Glue instrui o S3 a já retornar apenas os arquivos da pasta "year=XXXX/".
        # Isso é muito mais rápido e barato para tabelas grandes com vários anos.
        kwargs["push_down_predicate"] = f"year = '{year}'"
        logger.info(f"Aplicando filtro de partição: year = '{year}'")
    return glue_context.create_dynamic_frame.from_catalog(**kwargs)


def evaluate_data_quality(
    glue_context: GlueContext,
    dynamic_frame,
    ruleset: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
):
    """
    Avalia as regras DQDL contra o DynamicFrame e retorna DataFrame com resultados.

    Colunas do resultado: rule, outcome, failure_reason, evaluated_metrics,
    category, year, datetime_process, source_database, source_table.

    Args:
        glue_context:  Contexto do Glue.
        dynamic_frame: DynamicFrame com os dados da tabela lida do Catalog.
        ruleset:       String de regras no formato DQDL.
        table_name:    Nome da tabela avaliada.
        database:      Nome do banco de dados no Glue Catalog.
        year:          Ano da partição. Preenchido para tabelas com partição por ano (discover, details, watch_providers).

    Returns:
        Spark DataFrame com os resultados da avaliação e colunas de contexto.
    """
    logger.info(f"Avaliando qualidade de dados da tabela '{table_name}'...")

    # Para tabelas com partição por ano, aplica filtro duplo:
    # 1. push_down_predicate no read_table_from_catalog (filtro no S3 — evita ler arquivos errados)
    # 2. Este filtro no DataFrame Spark (garante que apenas linhas do ano correto são avaliadas)
    # O filtro duplo é necessário porque o Glue Catalog às vezes inclui metadados de outras
    # partições no cache, então o push_down_predicate sozinho pode não ser suficiente.
    if year is not None:
        df_source = dynamic_frame.toDF().filter(col("year") == year)
        dynamic_frame = DynamicFrame.fromDF(df_source, glue_context, "filtered_frame")
        logger.info(f"Filtro aplicado no DataFrame: year = '{year}'")

    dq_results = EvaluateDataQuality.apply(
        frame=dynamic_frame,
        ruleset=ruleset,
        publishing_options={
            "dataQualityEvaluationContext": table_name,
            "enableDataQualityCloudWatchMetrics": True,
            "enableDataQualityResultsPublishing": True,
        },
    )

    # Glue DQ devolve colunas em PascalCase; Athena espera snake_case para ler failure_reason corretamente.
    df = (
        dq_results.toDF()
        .withColumnRenamed("Rule", "rule")
        .withColumnRenamed("Outcome", "outcome")
        .withColumnRenamed("FailureReason", "failure_reason")
        .withColumnRenamed("EvaluatedMetrics", "evaluated_metrics")
        .drop(
            "EvaluatedRule"
        )  # coluna interna do Glue DQ que não faz parte do nosso schema
    )

    # EvaluatedMetrics é map<string, double> — o Wrangler não serializa esse tipo em Parquet.
    df = df.withColumn("evaluated_metrics", col("evaluated_metrics").cast(StringType()))
    # failure_reason fica totalmente nulo quando todas as regras passam;
    # sem cast explícito, toPandas() gera dtype object e o Wrangler não infere o tipo Athena.
    df = df.withColumn("failure_reason", col("failure_reason").cast(StringType()))

    # Classifica cada regra pela dimensão de qualidade com base no prefixo DQDL
    # para permitir filtros no Athena (ex: "Quais regras de Completude falharam?").
    df = df.withColumn(
        "category",
        when(col("rule").startswith("IsComplete"), "Completude")
        .when(col("rule").startswith("IsUnique"), "Unicidade")
        .when(col("rule").startswith("Uniqueness"), "Unicidade")
        .when(col("rule").startswith("ColumnValues"), "Validade")
        .when(col("rule").startswith("RowCount"), "Integridade"),
    )

    df = df.withColumn("year", lit(year).cast(StringType()))
    df = df.withColumn(
        "datetime_process", from_utc_timestamp(current_timestamp(), "America/Sao_Paulo")
    )
    df = df.withColumn("source_database", lit(database))
    df = df.withColumn("source_table", lit(table_name))

    logger.info(f"Avaliação concluída. Regras avaliadas: {df.count()}")
    return df


def write_results_to_s3(
    df,
    s3_bucket_data_quality: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> None:
    """
    Grava os resultados DQ em tb_data_quality_tmdb.

    Sempre particiona por ["source_table", "year"], garantindo estrutura uniforme
    no Glue Catalog (evita o erro do Athena "partition value count must match
    partition column count"). Tabelas sem partição por ano usam year="sem_ano"
    como valor fixo, preservando o comportamento de overwrite_partitions sem
    misturar partições com 1 e 2 níveis.

    Args:
        df:                     Spark DataFrame com os resultados da avaliação.
        s3_bucket_data_quality: Nome do bucket de Data Quality.
        table_name:             Nome da tabela avaliada.
        database:               Nome do banco de dados no Glue Catalog.
        year:                   Ano da partição. None para tabelas sem partição por ano.
    """
    output_table = "tb_data_quality_tmdb"
    s3_path = f"s3://{s3_bucket_data_quality}/tmdb/{output_table}/"

    if year is None:
        df = df.fillna({"year": "sem_ano"})

    logger.info(
        f"Gravando resultados em {s3_path} | source_table='{table_name}' | year='{year}'"
    )

    pandas_df = df.toPandas()
    pandas_df["failure_reason"] = pandas_df["failure_reason"].astype("string")

    wr.s3.to_parquet(
        df=pandas_df,
        path=s3_path,
        dataset=True,
        database=database,
        table=output_table,
        partition_cols=["source_table", "year"],
        mode="overwrite_partitions",
    )

    logger.info(f"Resultados de '{table_name}' gravados com sucesso!")


def notify_failed_outcomes(
    df,
    table_name: str,
    sns_topic_arn: str,
    environment: str,
    year: Optional[str] = None,
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
        year:          Partição avaliada, se aplicável.
    """
    failed_df = df.filter(col("outcome") == "Failed")
    count = failed_df.count()

    if count == 0:
        logger.info(f"Todas as regras passaram para '{table_name}'.")
        return

    first_row = df.select("datetime_process", "source_database").first()
    datetime_process = first_row["datetime_process"]
    source_database = first_row["source_database"]

    rows = failed_df.select("rule", "failure_reason", "category").collect()

    lines = [
        "[DQ Métrica Falha]",
        f"Ambiente: {environment}",
        f"Banco: {source_database}",
        f"Tabela: {table_name}",
        f"Data/Hora: {datetime_process.strftime('%d/%m/%Y %H:%M:%S')}",
    ]
    if year is not None:
        lines.append(f"Partição: year={year}")
    lines.append(f"Regras com falha ({count}):")
    for row in rows:
        lines.append(f"  • [{row['category']}] {row['rule']} → {row['failure_reason']}")

    message = "\n".join(lines)

    boto3.client("sns").publish(
        TopicArn=sns_topic_arn,
        Subject=f"[{environment.upper()}] DQ Métrica Falha",
        Message=message,
    )
    logger.warning(f"{count} regra(s) falharam para '{table_name}'. Notificação SNS enviada.")
