"""
backfill_traducao.py — Adiciona overview_pt, tagline_pt e keywords_pt aos
detalhes históricos.

Lê tb_details_movie_tmdb e tb_details_tv_tmdb ano a ano e traduz para
português, via Google Translate ou AWS Translate (TRANSLATE_PROVIDER — ver
abaixo), os campos ainda pendentes (espelhando o que o Glue Details faz para
dados novos). As três colunas usam a mesma regra de
elegibilidade: qualquer idioma original diferente de pt (evita reenviar à
API conteúdo que já está em português):
  - overview_pt:  original_language != 'pt' e overview_en preenchido
  - tagline_pt:   original_language != 'pt' e tagline preenchida
  - keywords_pt:  original_language != 'pt' e keywords preenchidas (a API do
                   TMDB sempre devolve keywords em inglês para os demais
                   idiomas)
Um campo é considerado "já traduzido" (e não é retraduzido) quando a coluna
_pt está preenchida e é diferente da coluna de origem. Campos sem tradução,
ou cuja coluna _pt ficou igual à de origem (fallback de uma tradução que
falhou em um run anterior — ver shared_utils/traducao.py), continuam
pendentes e são (re)tentados. Não é gerado collection_name_pt — diferente
dos demais, ele vem de uma chamada à API do TMDB (não do Google Translate) e
foi deixado fora deste script. Não re-chama a API do TMDB para os campos acima.

Leitura feita diretamente do S3 (parquet) — sem Athena/CTAS — para evitar
necessidade de athena:GetWorkGroup e glue:DeleteTable no usuário prod_temp.

Uso:
    python scripts/backfill_traducao.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    TABLE_GROUP            (identifica o checkpoint; valor "traducao" neste script)
    S3_BUCKET_SOT          (parquets reais de tb_details_movie/tv_tmdb e tb_discover_movie/tv_tmdb)
    S3_BUCKET_TEMP         (onde o checkpoint de retomada é armazenado)
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DETAILS_MOVIE
    TABLE_DETAILS_TV
    TABLE_DISCOVER_MOVIE
    TABLE_DISCOVER_TV

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
    BACKFILL_WAIT_SECONDS (padrão: 300 — pausa entre partições para não saturar Google Translate)
    TRANSLATE_PROVIDER    (padrão: "google" — grátis, mas instável sob alto volume;
                            "aws" usa AWS Translate, API oficial paga por caractere,
                            útil para testar um período menor via BACKFILL_START_YEAR/
                            BACKFILL_END_YEAR)

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken
    do S3), o script sai com exit code 75
    (backfill_shared.RETRYABLE_EXIT_CODE). O workflow renova a credencial
    e roda o script de novo — como o progresso é lido do checkpoint em S3
    (s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{TABLE_GROUP}.json), as
    partições (ano+tipo) já concluídas são puladas.
"""

import os
import sys
import time
from pathlib import Path

from typing import Callable, Optional

import awswrangler as wr
import boto3
import pandas as pd
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "shared_src"))
from shared_utils.traducao import (  # noqa: E402
    eligible_keywords_pt,
    eligible_overview_pt,
    eligible_tagline_pt,
    resolve_translate_fn,
    translate_pending_column,
    translate_text,
    translate_text_aws,  # noqa: F401 — reexportado para os testes verificarem identidade
)

import backfill_shared as shared

logger = shared.setup_logging()

_TRANSLATE_MAX_WORKERS = 10


def _traduzir_pendentes(
    df: pd.DataFrame,
    coluna_fonte: str,
    coluna_pt: str,
    mask_elegivel: "pd.Series[bool]",
    traduzir_fn: Callable[[str], str],
) -> int:
    """Traduz coluna_fonte → coluna_pt para os registros elegíveis ainda pendentes
    (ver translate_pending_column em shared_utils/traducao.py para a regra de
    "já traduzido" — pulado — e o retry entre execuções do backfill)."""
    logger.info(
        "  Traduzindo até %d registros para %s (%d workers)...",
        mask_elegivel.sum(), coluna_pt, _TRANSLATE_MAX_WORKERS,
    )
    sucesso = translate_pending_column(
        df, coluna_fonte, coluna_pt, mask_elegivel, traduzir_fn, max_workers=_TRANSLATE_MAX_WORKERS
    )
    logger.info("  %d traduzidos com sucesso (%s).", sucesso, coluna_pt)
    return sucesso


def _adicionar_traducoes_pt(df: pd.DataFrame, traduzir_fn: Optional[Callable[[str], str]] = None) -> tuple[pd.DataFrame, int]:
    """Adiciona overview_pt aos registros com idioma original diferente de pt e
    overview_en preenchido, ainda pendentes (registros com overview_en vazio não
    têm o que traduzir e distorceriam a contagem de sucesso)."""
    # traduzir_fn resolvido em runtime (não como default de parâmetro) para que
    # patch("backfill_traducao.translate_text", ...) nos testes continue funcionando
    # quando o chamador não passa um traduzir_fn explícito.
    traduzir_fn = traduzir_fn or translate_text
    if "overview_pt" not in df.columns:
        df["overview_pt"] = None

    mask_elegivel = eligible_overview_pt(df)
    if not mask_elegivel.any():
        return df, 0
    sucesso = _traduzir_pendentes(df, "overview_en", "overview_pt", mask_elegivel, traduzir_fn)
    return df, sucesso


def _adicionar_traducoes_tagline_pt(df: pd.DataFrame, traduzir_fn: Optional[Callable[[str], str]] = None) -> tuple[pd.DataFrame, int]:
    """Adiciona tagline_pt aos registros com tagline preenchida e idioma original
    diferente de pt (espelha glue_details)."""
    traduzir_fn = traduzir_fn or translate_text
    if "tagline" not in df.columns:
        return df, 0
    mask_elegivel = eligible_tagline_pt(df)
    if not mask_elegivel.any():
        return df, 0
    sucesso = _traduzir_pendentes(df, "tagline", "tagline_pt", mask_elegivel, traduzir_fn)
    return df, sucesso


def _adicionar_traducoes_keywords_pt(df: pd.DataFrame, traduzir_fn: Optional[Callable[[str], str]] = None) -> tuple[pd.DataFrame, int]:
    """Adiciona keywords_pt aos registros com keywords preenchidas e idioma original
    diferente de pt (TMDB sempre devolve keywords em inglês para os demais idiomas)."""
    traduzir_fn = traduzir_fn or translate_text
    if "keywords" not in df.columns:
        return df, 0
    mask_elegivel = eligible_keywords_pt(df)
    if not mask_elegivel.any():
        return df, 0
    sucesso = _traduzir_pendentes(df, "keywords", "keywords_pt", mask_elegivel, traduzir_fn)
    return df, sucesso


def _load_discover_map(table_discover: str, s3_bucket_sot: str) -> pd.DataFrame:
    """Lê toda a tabela discover do S3 e retorna DataFrame id→original_language único."""
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_discover}/"
    logger.info("  Carregando discover de %s...", s3_path)
    try:
        df = wr.s3.read_parquet(path=s3_path, columns=["id", "original_language"])
    except ClientError as exc:
        shared.log_expired_token(exc, f"leitura de {s3_path}")
        raise
    return df.drop_duplicates(subset=["id"])[["id", "original_language"]].reset_index(drop=True)


def _backfill_year(
    database: str,
    table_details: str,
    discover_map: pd.DataFrame,
    year: str,
    s3_bucket_sot: str,
    traduzir_fn: Optional[Callable[[str], str]] = None,
) -> tuple[bool, int]:
    """
    Lê uma partição de year em tb_details_* diretamente do S3, adiciona
    traduções PT e reescreve. Usa S3 em vez de Athena/CTAS para evitar
    permissões athena:GetWorkGroup e glue:DeleteTable.

    Returns:
        Tupla (escreveu, quantidade traduzida com sucesso).
    """
    traduzir_fn = traduzir_fn or translate_text
    s3_details_path = f"s3://{s3_bucket_sot}/tmdb/{table_details}/year={year}/"

    try:
        df = wr.s3.read_parquet(path=s3_details_path)
    except ClientError as exc:
        shared.log_expired_token(exc, f"leitura de {s3_details_path}")
        raise
    except Exception as exc:
        if "NoFilesFound" in type(exc).__name__ or "NoFilesFound" in str(exc):
            logger.info("  Nenhum arquivo em %s. Pulando.", s3_details_path)
            return False, 0
        raise

    if df.empty:
        logger.info("  Nenhum registro para year=%s. Pulando.", year)
        return False, 0

    logger.info("  %d registros lidos.", len(df))

    df = df.merge(discover_map, on="id", how="left")
    df["original_language"] = df["original_language"].fillna("und")

    df, sucesso_overview = _adicionar_traducoes_pt(df, traduzir_fn)
    df, sucesso_tagline = _adicionar_traducoes_tagline_pt(df, traduzir_fn)
    df, sucesso_keywords = _adicionar_traducoes_keywords_pt(df, traduzir_fn)
    traduzidos = sucesso_overview + sucesso_tagline + sucesso_keywords
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
        shared.log_expired_token(exc, f"escrita de {s3_path} (year={year})")
        raise
    logger.info("  %d registros escritos em %s (year=%s).", len(df), s3_path, year)
    return True, traduzidos


def main() -> None:
    region = shared.require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region

    table_group          = shared.require_env("TABLE_GROUP")
    s3_bucket_sot         = shared.require_env("S3_BUCKET_SOT")
    s3_bucket_temp        = shared.require_env("S3_BUCKET_TEMP")
    db_movie              = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv                 = shared.require_env("GLUE_DATABASE_TV")
    table_details_movie   = shared.require_env("TABLE_DETAILS_MOVIE")
    table_details_tv      = shared.require_env("TABLE_DETAILS_TV")
    table_discover_movie  = shared.require_env("TABLE_DISCOVER_MOVIE")
    table_discover_tv     = shared.require_env("TABLE_DISCOVER_TV")

    start_year, end_year = shared.read_year_range(end_env="BACKFILL_END_YEAR")
    wait_seconds = int(os.environ.get("BACKFILL_WAIT_SECONDS", 300))
    translate_provider = os.environ.get("TRANSLATE_PROVIDER", "google")

    years = list(range(start_year, end_year + 1))
    total = len(years) * 2
    logger.info(
        "Backfill de tradução: %d até %d | %d partições (movie + tv) | pausa=%ds entre partições "
        "| serviço de tradução=%s",
        start_year, end_year, total, wait_seconds, translate_provider,
    )
    # Um único traduzir_fn para toda a execução (não por partição) — mesmo serviço de
    # tradução para todas as partições ano+tipo do run.
    traduzir_fn = resolve_translate_fn(translate_provider, translate_text, translate_text_aws)

    s3_client = boto3.client("s3", region_name=region)

    logger.info("Carregando tabelas discover do S3...")
    discover_map_movie = _load_discover_map(table_discover_movie, s3_bucket_sot)
    discover_map_tv    = _load_discover_map(table_discover_tv, s3_bucket_sot)
    logger.info(
        "  movie: %d ids únicos | tv: %d ids únicos",
        len(discover_map_movie), len(discover_map_tv),
    )

    completed = shared.load_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year)

    unidades = []
    for year in years:
        unidades.append(("movie", year, db_movie, table_details_movie, discover_map_movie))
        unidades.append(("tv", year, db_tv, table_details_tv, discover_map_tv))

    pendentes = [u for u in unidades if f"{u[0]}:{u[1]}" not in completed]
    shared.log_resume_progress(logger, "partições já concluídas", len(unidades), len(pendentes))

    total_traduzidos = 0
    for i, (tipo, year, database, table_details, discover_map) in enumerate(pendentes, start=1):
        logger.info("[%d/%d] %s | year=%d", i, len(pendentes), tipo, year)
        _, traduzidos = _backfill_year(
            database=database,
            table_details=table_details,
            discover_map=discover_map,
            year=str(year),
            s3_bucket_sot=s3_bucket_sot,
            traduzir_fn=traduzir_fn,
        )
        total_traduzidos += traduzidos
        completed.add(f"{tipo}:{year}")
        shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)
        if i < len(pendentes):
            logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)
            time.sleep(wait_seconds)

    shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)
    logger.info(
        "Backfill de tradução concluído: %d até %d | %d campos traduzidos com sucesso "
        "(overview_pt + tagline_pt + keywords_pt)",
        start_year, end_year, total_traduzidos,
    )


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
