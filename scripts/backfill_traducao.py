"""
backfill_traducao.py — Adiciona title_pt/overview_pt aos detalhes históricos.

Lê tb_details_movie_tmdb e tb_details_tv_tmdb ano a ano, traduz title_en e
overview_en para português (apenas registros com original_language='en') e
reescreve a partição com as novas colunas. Não re-chama a API do TMDB.

Leitura feita diretamente do S3 (parquet) — sem Athena/CTAS — para evitar
necessidade de athena:GetWorkGroup e glue:DeleteTable no usuário prod_temp.

Uso:
    python scripts/backfill_traducao.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
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
    BACKFILL_WAIT_SECONDS  (padrão: 30 — pausa entre partições para não saturar Google Translate)
"""

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import awswrangler as wr
import pandas as pd
from deep_translator import GoogleTranslator

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


def _translate(texto: str) -> str:
    """Traduz texto EN→PT via Google Translate com até 3 tentativas."""
    if not texto:
        return ""
    for tentativa in range(1, 4):
        try:
            resultado = GoogleTranslator(source="en", target="pt").translate(texto)
            if resultado:
                return resultado
        except Exception as exc:
            logger.debug("Tentativa %d falhou: %s", tentativa, exc)
        time.sleep(tentativa * 2)
    logger.warning("Falha ao traduzir após 3 tentativas: %.80s...", texto)
    return texto


def _adicionar_traducoes_pt(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona title_pt e overview_pt; traduz apenas original_language='en'."""
    df["title_pt"] = None
    df["overview_pt"] = None

    mask = df["original_language"] == "en"
    if not mask.any():
        return df

    total = mask.sum()
    logger.info("  Traduzindo %d registros EN→PT (%d workers)...", total, _TRANSLATE_MAX_WORKERS)

    for col_en, col_pt in (("title_en", "title_pt"), ("overview_en", "overview_pt")):
        valores = df.loc[mask, col_en].fillna("").tolist()
        with ThreadPoolExecutor(max_workers=_TRANSLATE_MAX_WORKERS) as executor:
            traduzidos = list(executor.map(_translate, valores))
        df.loc[mask, col_pt] = traduzidos

    return df


def _load_discover_map(table_discover: str, s3_bucket_sot: str) -> pd.DataFrame:
    """Lê toda a tabela discover do S3 e retorna DataFrame id→original_language único."""
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_discover}/"
    logger.info("  Carregando discover de %s...", s3_path)
    df = wr.s3.read_parquet(path=s3_path, columns=["id", "original_language"])
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
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        partition_cols=["year"],
        mode="overwrite_partitions",
        database=database,
        table=table_details,
    )
    logger.info("  %d registros escritos em %s (year=%s).", len(df), s3_path, year)
    return True


def main() -> None:
    os.environ["AWS_DEFAULT_REGION"] = _require_env("AWS_REGION")

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

    logger.info("Carregando tabelas discover do S3...")
    discover_map_movie = _load_discover_map(table_discover_movie, s3_bucket_sot)
    discover_map_tv    = _load_discover_map(table_discover_tv, s3_bucket_sot)
    logger.info(
        "  movie: %d ids únicos | tv: %d ids únicos",
        len(discover_map_movie), len(discover_map_tv),
    )

    n = 0
    for year in years:
        n += 1
        logger.info("[%d/%d] movie | year=%d", n, total, year)
        _backfill_year(
            database=db_movie,
            table_details=table_details_movie,
            discover_map=discover_map_movie,
            year=str(year),
            s3_bucket_sot=s3_bucket_sot,
        )
        if n < total:
            logger.info("Aguardando %ds...", wait_seconds)
            time.sleep(wait_seconds)

        n += 1
        logger.info("[%d/%d] tv    | year=%d", n, total, year)
        _backfill_year(
            database=db_tv,
            table_details=table_details_tv,
            discover_map=discover_map_tv,
            year=str(year),
            s3_bucket_sot=s3_bucket_sot,
        )
        if n < total:
            logger.info("Aguardando %ds...", wait_seconds)
            time.sleep(wait_seconds)

    logger.info("Backfill de tradução concluído: %d até %d", start_year, end_year)


if __name__ == "__main__":
    main()
