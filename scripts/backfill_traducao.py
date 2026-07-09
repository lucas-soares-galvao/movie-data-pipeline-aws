"""
backfill_traducao.py — Adiciona overview_pt aos detalhes históricos.

Lê tb_details_movie_tmdb e tb_details_tv_tmdb ano a ano, traduz overview_en
para português (apenas registros com original_language='en') e reescreve a
partição com a nova coluna. Não re-chama a API do TMDB.

Leitura feita diretamente do S3 (parquet) — sem Athena/CTAS — para evitar
necessidade de athena:GetWorkGroup e glue:DeleteTable no usuário prod_temp.

Uso:
    python scripts/backfill_traducao.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    TABLE_GROUP            (identifica o checkpoint; valor "traducao" neste script)
    S3_BUCKET_SOT
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DETAILS_MOVIE
    TABLE_DETAILS_TV
    TABLE_DISCOVER_MOVIE
    TABLE_DISCOVER_TV

Variáveis opcionais:
    BACKFILL_START_YEAR    (padrão: 2000)
    BACKFILL_END_YEAR      (padrão: ano atual)
    BACKFILL_WAIT_SECONDS  (padrão: 300 — pausa entre partições para não saturar Google Translate)

Retomada automática:
    Se ExpiredTokenException ocorrer, o script sai com exit code 75
    (backfill_checkpoint.RETRYABLE_EXIT_CODE). O workflow renova a credencial
    e roda o script de novo — como o progresso é lido do checkpoint em S3
    (s3://{S3_BUCKET_SOT}/_backfill_checkpoints/{TABLE_GROUP}.json), as
    partições (ano+tipo) já concluídas são puladas.
"""

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import awswrangler as wr
import boto3
import pandas as pd
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "shared_src"))
from shared_utils.traducao import traduzir_texto  # noqa: E402

import backfill_checkpoint as checkpoint

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger()

_TRANSLATE_MAX_WORKERS = 10


def _require_env(name: str) -> str:
    """Lê variável de ambiente obrigatória ou levanta erro."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def _log_expired_token(exc: ClientError, contexto: str) -> None:
    """Loga um erro claro se a credencial AWS expirou durante o backfill."""
    if exc.response.get("Error", {}).get("Code") == "ExpiredTokenException":
        logger.error(
            "Credenciais AWS expiraram durante %s. O workflow vai renovar a credencial "
            "e retomar do checkpoint automaticamente (ver scripts/backfill_checkpoint.py).",
            contexto,
        )


def _adicionar_traducoes_pt(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona overview_pt; traduz apenas original_language='en'."""
    df["overview_pt"] = None

    mask = df["original_language"] == "en"
    if not mask.any():
        return df

    total = mask.sum()
    logger.info("  Traduzindo %d registros EN→PT (%d workers)...", total, _TRANSLATE_MAX_WORKERS)

    valores = df.loc[mask, "overview_en"].fillna("").tolist()
    with ThreadPoolExecutor(max_workers=_TRANSLATE_MAX_WORKERS) as executor:
        traduzidos = list(executor.map(traduzir_texto, valores))
    df.loc[mask, "overview_pt"] = traduzidos

    return df


def _load_discover_map(table_discover: str, s3_bucket_sot: str) -> pd.DataFrame:
    """Lê toda a tabela discover do S3 e retorna DataFrame id→original_language único."""
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_discover}/"
    logger.info("  Carregando discover de %s...", s3_path)
    try:
        df = wr.s3.read_parquet(path=s3_path, columns=["id", "original_language"])
    except ClientError as exc:
        _log_expired_token(exc, f"leitura de {s3_path}")
        raise
    return df.drop_duplicates(subset=["id"])[["id", "original_language"]].reset_index(drop=True)


def _backfill_year(
    database: str,
    table_details: str,
    discover_map: pd.DataFrame,
    year: str,
    s3_bucket_sot: str,
) -> bool:
    """
    Lê uma partição de year em tb_details_* diretamente do S3, adiciona
    traduções PT e reescreve. Usa S3 em vez de Athena/CTAS para evitar
    permissões athena:GetWorkGroup e glue:DeleteTable.
    """
    s3_details_path = f"s3://{s3_bucket_sot}/tmdb/{table_details}/year={year}/"

    try:
        df = wr.s3.read_parquet(path=s3_details_path)
    except ClientError as exc:
        _log_expired_token(exc, f"leitura de {s3_details_path}")
        raise
    except Exception as exc:
        if "NoFilesFound" in type(exc).__name__ or "NoFilesFound" in str(exc):
            logger.info("  Nenhum arquivo em %s. Pulando.", s3_details_path)
            return False
        raise

    if df.empty:
        logger.info("  Nenhum registro para year=%s. Pulando.", year)
        return False

    logger.info("  %d registros lidos.", len(df))

    df = df.merge(discover_map, on="id", how="left")
    df["original_language"] = df["original_language"].fillna("und")

    df = _adicionar_traducoes_pt(df)
    df = df.drop(columns=["original_language"])
    df["year"] = year

    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_details}/"
    try:
        wr.s3.to_parquet(
            df=df,
            path=s3_path,
            dataset=True,
            partition_cols=["year"],
            mode="overwrite_partitions",
            database=database,
            table=table_details,
        )
    except ClientError as exc:
        _log_expired_token(exc, f"escrita de {s3_path} (year={year})")
        raise
    logger.info("  %d registros escritos em %s (year=%s).", len(df), s3_path, year)
    return True


def main() -> None:
    region = _require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region

    table_group          = _require_env("TABLE_GROUP")
    s3_bucket_sot        = _require_env("S3_BUCKET_SOT")
    db_movie             = _require_env("GLUE_DATABASE_MOVIE")
    db_tv                = _require_env("GLUE_DATABASE_TV")
    table_details_movie  = _require_env("TABLE_DETAILS_MOVIE")
    table_details_tv     = _require_env("TABLE_DETAILS_TV")
    table_discover_movie = _require_env("TABLE_DISCOVER_MOVIE")
    table_discover_tv    = _require_env("TABLE_DISCOVER_TV")

    start_year   = int(os.environ.get("BACKFILL_START_YEAR",   2000))
    end_year     = int(os.environ.get("BACKFILL_END_YEAR",     datetime.now().year))
    wait_seconds = int(os.environ.get("BACKFILL_WAIT_SECONDS", 300))

    years = list(range(start_year, end_year + 1))
    total = len(years) * 2
    logger.info(
        "Backfill de tradução: %d até %d | %d partições (movie + tv) | pausa=%ds entre partições",
        start_year, end_year, total, wait_seconds,
    )

    s3_client = boto3.client("s3", region_name=region)

    logger.info("Carregando tabelas discover do S3...")
    discover_map_movie = _load_discover_map(table_discover_movie, s3_bucket_sot)
    discover_map_tv    = _load_discover_map(table_discover_tv, s3_bucket_sot)
    logger.info(
        "  movie: %d ids únicos | tv: %d ids únicos",
        len(discover_map_movie), len(discover_map_tv),
    )

    completed = checkpoint.load_checkpoint(s3_client, s3_bucket_sot, table_group, start_year, end_year)

    unidades = []
    for year in years:
        unidades.append(("movie", year, db_movie, table_details_movie, discover_map_movie))
        unidades.append(("tv", year, db_tv, table_details_tv, discover_map_tv))

    pendentes = [u for u in unidades if f"{u[0]}:{u[1]}" not in completed]
    if len(pendentes) < len(unidades):
        logger.info(
            "%d de %d partições já concluídas no checkpoint; retomando com %d pendente(s).",
            len(unidades) - len(pendentes), len(unidades), len(pendentes),
        )

    for i, (tipo, year, database, table_details, discover_map) in enumerate(pendentes, start=1):
        logger.info("[%d/%d] %s | year=%d", i, len(pendentes), tipo, year)
        _backfill_year(
            database=database,
            table_details=table_details,
            discover_map=discover_map,
            year=str(year),
            s3_bucket_sot=s3_bucket_sot,
        )
        completed.add(f"{tipo}:{year}")
        checkpoint.save_checkpoint(s3_client, s3_bucket_sot, table_group, start_year, end_year, completed)
        if i < len(pendentes):
            logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)
            time.sleep(wait_seconds)

    checkpoint.clear_checkpoint(s3_client, s3_bucket_sot, table_group)
    logger.info("Backfill de tradução concluído: %d até %d", start_year, end_year)


if __name__ == "__main__":
    try:
        main()
    except ClientError as exc:
        codigo = checkpoint.expired_token_exit_code(exc)
        if codigo is not None:
            sys.exit(codigo)
        raise
