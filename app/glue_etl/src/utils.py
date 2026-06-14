"""utils.py — Funções auxiliares do Glue ETL."""

import json
import logging
import sys
from typing import Any, Dict, List, Optional

import boto3
import awswrangler as wr
import pandas as pd
from awsglue.utils import getResolvedOptions

SOR_KEYS = {
    "movie": {
        "genre":                "tmdb/genre/movie/generos_filmes.json",
        "configuration":        "tmdb/configuration/languages/idiomas.json",
        "discover":             "tmdb/discover/movie/ano={year}/",
        "watch_providers_ref":  "tmdb/watch_providers_ref/movie/watch_providers_ref.json",
        "now_playing":          "tmdb/now_playing/movie/",
    },
    "tv": {
        "genre":                "tmdb/genre/tv/generos_series.json",
        "configuration":        "tmdb/configuration/countries/paises.json",
        "discover":             "tmdb/discover/tv/ano={year}/",
        "watch_providers_ref":  "tmdb/watch_providers_ref/tv/watch_providers_ref.json",
    },
}

# A TMDB retorna variações do mesmo serviço (ex: "Netflix", "Netflix basic with Ads").
# Estratégia: remove sufixos comuns, depois aplica overrides manuais para casos especiais.
_CANONICAL_SUFFIXES = [
    " Amazon Channel",
    " Apple TV Channel",
    " Apple Channel",
    " Plus Premium",
    " Premium",
    " Standard with Ads",
    " with Ads",
]

_CANONICAL_OVERRIDES = {
    "Paramount Plus": "Paramount+",
    "Paramount":      "Paramount+",   # "Paramount Plus Premium" → strip " Plus Premium" → aqui
    "MGM Plus":       "MGM+",         # "MGM Plus Amazon Channel" → strip sufixo → aqui
    "Claro video":    "Claro Video",  # Padroniza capitalização
}


def derive_canonical_name(name: str) -> str:
    """
    Normaliza o nome de uma plataforma removendo sufixos de variante.

    Ex: "Netflix Standard with Ads" → "Netflix", "Paramount Plus Premium" → "Paramount+"

    Args:
        name: Nome original retornado pela API TMDB

    Returns:
        Nome canônico normalizado
    """
    result = name.strip()
    lower = result.lower()

    # Remove o primeiro sufixo que corresponder (por ordem de especificidade)
    for suffix in _CANONICAL_SUFFIXES:
        if lower.endswith(suffix.lower()):
            result = result[: -len(suffix)]  # Remove os últimos N caracteres
            break

    # Aplica override manual se o resultado estiver na lista
    return _CANONICAL_OVERRIDES.get(result, result)


logger = logging.getLogger()


def get_resolved_option(args: list) -> Dict[str, Any]:
    """Wrapper de getResolvedOptions — converte lista de nomes em dicionário nome→valor."""
    return getResolvedOptions(sys.argv, args)


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê todos os argumentos do job Glue ETL e retorna em um dicionário.

    Returns:
        Dicionário com todos os argumentos disponíveis nesta execução
    """
    required_args = [
        "S3_BUCKET_SOR",
        "S3_BUCKET_SOT",
        "MEDIA_TYPE",
        "DATABASE",
        "TABLE_NAME",
        "TABLE_TYPE",
        "GLUE_DATA_QUALITY_JOB_NAME",
        "GLUE_AGG_JOB_NAME",
        "GLUE_DETAILS_JOB_NAME",
    ]
    args = get_resolved_option(required_args)

    # Tenta ler YEAR e END_YEAR — só presentes nos runs de discover
    try:
        args.update(get_resolved_option(["YEAR", "END_YEAR"]))
    except SystemExit:
        pass  # Argumentos opcionais ausentes — comportamento esperado para genre/config

    return args


def read_from_sor(
    s3_bucket_sor: str,
    media_type: str,
    table_type: str,
    year: Optional[str] = None,
) -> pd.DataFrame:
    """
    Lê dados do bucket SOR e retorna como DataFrame Pandas.

    discover: lê pasta inteira com wr.s3.read_json, adiciona coluna year, remove duplicatas por id.
    watch_providers_ref: lê arquivo único, deriva canonical_name.
    genre / configuration: lê arquivo único diretamente.

    Args:
        s3_bucket_sor: Nome do bucket SOR
        media_type:    "movie" ou "tv"
        table_type:    Tipo da tabela (determina como ler)
        year:          Ano para o discover (ex: "2024")

    Returns:
        DataFrame com os dados lidos e prontos para gravação no SOT
    """
    s3_key = SOR_KEYS[media_type][table_type].format(year=year)
    logger.info(f"Lendo {table_type} de s3://{s3_bucket_sor}/{s3_key}")

    if table_type == "discover":
        df = wr.s3.read_json(path=f"s3://{s3_bucket_sor}/{s3_key}", orient="records")
        df["year"] = year
        df = df.drop_duplicates(subset=["id"])

    elif table_type == "now_playing":
        df = wr.s3.read_json(path=f"s3://{s3_bucket_sor}/{s3_key}", orient="records")
        df = df.drop_duplicates(subset=["id"])

    elif table_type == "watch_providers_ref":
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=s3_bucket_sor, Key=s3_key)
        data = json.loads(response["Body"].read())
        df = pd.DataFrame(data)
        df["canonical_name"] = df["provider_name"].apply(derive_canonical_name)

    else:
        s3_client = boto3.client("s3")
        response = s3_client.get_object(Bucket=s3_bucket_sor, Key=s3_key)
        data = json.loads(response["Body"].read())
        df = pd.DataFrame(data)

    logger.info(f"Lidos {len(df)} registros.")
    return df


def write_parquet_to_sot(
    df: pd.DataFrame,
    s3_bucket_sot: str,
    table_name: str,
    database: str,
    partition_cols: Optional[List[str]] = None,
    mode: str = "overwrite_partitions",
) -> None:
    """
    Grava um DataFrame como Parquet no SOT e atualiza o Glue Catalog via AWS Wrangler.

    Args:
        df:             DataFrame com os dados transformados
        s3_bucket_sot:  Nome do bucket SOT de destino
        table_name:     Nome da tabela no Catalog
        database:       Nome do banco no Catalog
        partition_cols: Lista de colunas de partição (ex: ["year"]) ou None
        mode:           "overwrite_partitions" ou "overwrite"
    """
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    logger.info(
        f"Escrevendo {len(df)} registros em {s3_path} | particao={partition_cols} | mode={mode}"
    )
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=partition_cols,
        mode=mode,
        database=database,
        table=table_name,
    )
    logger.info(f"Tabela '{table_name}' atualizada com sucesso no SOT.")


def trigger_data_quality(
    dq_job_name: str,
    table_name: str,
    database: str,
    year: Optional[str] = None,
) -> str:
    """
    Dispara o job Glue Data Quality sem aguardar — roda em paralelo.

    Args:
        dq_job_name: Nome do job DQ registrado na AWS
        table_name:  Nome da tabela a validar
        database:    Banco no Glue Catalog
        year:        Ano da partição (para DQ validar apenas o ano recém-gravado)

    Returns:
        JobRunId da execução iniciada
    """
    arguments = {
        "--TABLE_NAME": table_name,
        "--DATABASE": database,
    }
    if year is not None:
        arguments["--YEAR"] = year

    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(
        JobName=dq_job_name,
        Arguments=arguments,
    )
    run_id = response["JobRunId"]
    logger.info(
        f"Job Data Quality '{dq_job_name}' iniciado para tabela '{table_name}'. RunId: {run_id}"
    )
    return run_id


def trigger_agg(agg_job_name: str) -> str:
    """
    Dispara o job Glue AGG.

    Args:
        agg_job_name: Nome do job AGG na AWS

    Returns:
        JobRunId da execução
    """
    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(JobName=agg_job_name)
    run_id = response["JobRunId"]
    logger.info(f"Job AGG '{agg_job_name}' iniciado. RunId: {run_id}")
    return run_id


def trigger_details(
    details_job_name: str,
    media_type: str,
    year: str,
    end_year: str,
    database: str,
) -> str:
    """
    Dispara o job Glue Details para enriquecer IDs do discover com dados da API TMDB.

    Args:
        details_job_name: Nome do job Details na AWS
        media_type:       "movie" ou "tv"
        year:             Ano do ciclo atual
        end_year:         Último ano do ciclo (o Details dispara AGG quando year==end_year)
        database:         Banco do Catalog correspondente ao media_type

    Returns:
        JobRunId da execução
    """
    glue_client = boto3.client("glue")
    response = glue_client.start_job_run(
        JobName=details_job_name,
        Arguments={
            "--MEDIA_TYPE": media_type,
            "--YEAR":       year,
            "--END_YEAR":   end_year,
            "--DATABASE":   database,
        },
    )
    run_id = response["JobRunId"]
    logger.info(f"Job Details '{details_job_name}' iniciado. RunId: {run_id}")
    return run_id
