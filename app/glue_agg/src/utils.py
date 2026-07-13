"""utils.py — Funções auxiliares do job Glue AGG."""

import logging
from typing import Any, Dict

import awswrangler as wr
import pandas as pd

from shared_utils.glue_helpers import get_resolved_option  # noqa: F401
from shared_utils.triggers import trigger_glue_job  # noqa: F401
from src.queries import _DISCOVER_UNIFIED_QUERY

logger = logging.getLogger()


def get_parameters_glue() -> Dict[str, Any]:
    """
    Lê os argumentos obrigatórios do job Glue AGG.

    Returns:
        Dicionário com todos os argumentos resolvidos.
    """
    required_args = [
        "S3_BUCKET_SPEC",
        "S3_PREFIX_SPEC",
        "S3_BUCKET_TEMP",
        "DB_MOVIE",
        "DB_TV",
        "DB_UNIFIED",
        "TABLE_NAME",
        "GLUE_DATA_QUALITY_JOB_NAME",
        "ENVIRONMENT",
    ]
    return get_resolved_option(required_args)


def _table_names(env: str) -> Dict[str, str]:
    """
    Constrói os nomes das tabelas do Glue Catalog a partir do ambiente.

    Returns:
        Dict com 13 chaves no formato {"tb_<sufixo>": "tb_tmdb_<sufixo>_<env>"}.
        Ex (env="dev"): {"tb_discover_movie": "tb_tmdb_discover_movie_dev",
                         "tb_genre_movie":    "tb_tmdb_genre_movie_dev", ...}
    """
    prefix = "tmdb"
    names = [
        "discover_movie",
        "discover_tv",
        "genre_movie",
        "genre_tv",
        "details_movie",
        "details_tv",
        "watch_providers_movie",
        "watch_providers_tv",
        "watch_providers_ref_movie",
        "watch_providers_ref_tv",
        "configuration_languages",
        "configuration_countries",
        "now_playing_movie",
    ]
    return {f"tb_{n}": f"tb_{prefix}_{n}_{env}" for n in names}


def run_athena_query(
    db_movie: str,
    db_tv: str,
    db_unified: str,
    s3_bucket_temp: str,
    env: str,
) -> pd.DataFrame:
    """
    Executa a query de unificação no Athena e retorna o resultado como DataFrame.

    Usa ctas_approach=True (Create Table As Select) para suportar colunas ARRAY.
    Sem CTAS, o Athena não consegue retornar colunas do tipo ARRAY via API direta.

    Args:
        db_movie:       Banco de dados de filmes no Glue Catalog.
        db_tv:          Banco de dados de séries no Glue Catalog.
        db_unified:     Banco de dados unificado.
        s3_bucket_temp: Bucket S3 para os resultados temporários do Athena.
        env:            Ambiente (dev/prod) para construir os nomes das tabelas.

    Returns:
        DataFrame com o resultado da query.
    """
    table_names = _table_names(env)  # {"tb_discover_movie": "tb_tmdb_discover_movie_dev", ...}
    query = _DISCOVER_UNIFIED_QUERY.format(
        db_movie=db_movie,
        db_tv=db_tv,
        db_unified=db_unified,
        **table_names,
    )
    s3_output = f"s3://{s3_bucket_temp}/tmdb/athena/glue_agg/"

    logger.info(
        f"Executando query Athena | db_movie='{db_movie}' | db_tv='{db_tv}' | db_unified='{db_unified}'"
    )
    df = wr.athena.read_sql_query(
        sql=query,
        database=db_unified,
        s3_output=s3_output,
        ctas_approach=True,
    )
    logger.info(f"Query executada com sucesso. {len(df)} registros retornados.")
    return df


def write_parquet_to_spec(
    df: pd.DataFrame,
    s3_bucket_spec: str,
    s3_prefix_spec: str,
    table_name: str,
    database: str,
) -> None:
    """
    Escreve o DataFrame como Parquet no bucket SPEC, particionado por media_type e year.

    Usa overwrite para garantir que o Glue Catalog fique sempre sincronizado com o S3.
    overwrite_partitions pode deixar o Catalog apontando para arquivos antigos deletados
    caso a atualização do Catalog falhe parcialmente após a deleção dos arquivos S3.
    Como a tabela unificada é sempre escrita por completo (todos os anos/media_types),
    overwrite e overwrite_partitions produzem o mesmo resultado final.

    Args:
        df:             DataFrame a ser gravado.
        s3_bucket_spec: Nome do bucket SPEC de destino.
        s3_prefix_spec: Prefixo do caminho S3 dentro do bucket SPEC.
        table_name:     Nome da tabela de destino no Catalog e como prefixo no S3.
        database:       Nome do banco de dados no Glue Catalog.
    """
    if df.empty:
        logger.warning(
            f"DataFrame vazio recebido para '{table_name}'. "
            "Escrita ignorada para preservar dados existentes."
        )
        return

    s3_path = f"s3://{s3_bucket_spec}/{s3_prefix_spec}/{table_name}/"
    logger.info(
        f"Escrevendo {len(df)} registros em {s3_path} | "
        f"particoes=[media_type, year] | mode=overwrite"
    )
    result = wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["media_type", "year"],
        mode="overwrite",
        database=database,
        table=table_name,
    )
    written_files = result.get("paths", [])
    if not written_files:
        raise RuntimeError(
            f"Escrita falhou: nenhum arquivo encontrado em '{s3_path}' após gravação. "
            "Abortando para não acionar o DQ contra dados ausentes."
        )
    logger.info(f"Tabela '{table_name}' gravada com sucesso no SPEC. {len(written_files)} arquivo(s) gravado(s).")
