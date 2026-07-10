"""
backfill_traducao.py — Adiciona overview_pt, tagline_pt e keywords_pt aos
detalhes históricos.

Lê tb_details_movie_tmdb e tb_details_tv_tmdb ano a ano e traduz para
português, via Google Translate, os campos ainda pendentes (espelhando o que
o Glue Details faz para dados novos):
  - overview_pt:  apenas original_language='en'
  - tagline_pt:   qualquer registro com tagline preenchida
  - keywords_pt:  qualquer registro com keywords preenchidas (a API do TMDB
                   sempre devolve keywords em inglês, independente do idioma
                   original do título)
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
    BACKFILL_START_YEAR    (padrão: 2000)
    BACKFILL_END_YEAR      (padrão: ano atual)
    BACKFILL_WAIT_SECONDS  (padrão: 300 — pausa entre partições para não saturar Google Translate)

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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import awswrangler as wr
import boto3
import pandas as pd
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "shared_src"))
from shared_utils.traducao import traduzir_texto  # noqa: E402

import backfill_shared as shared

logger = shared.setup_logging()

_TRANSLATE_MAX_WORKERS = 10


def _traduzir_pendentes(
    df: pd.DataFrame,
    coluna_fonte: str,
    coluna_pt: str,
    mask_elegivel: "pd.Series[bool]",
) -> int:
    """Traduz coluna_fonte → coluna_pt para os registros elegíveis ainda pendentes.

    Um registro é considerado "já traduzido" (e não é retraduzido) quando
    coluna_pt está preenchida e é diferente de coluna_fonte. Registros sem
    coluna_pt, ou cuja coluna_pt é igual a coluna_fonte (fallback de uma
    tradução que falhou em um run anterior — ver shared_utils/traducao.py),
    continuam pendentes e são (re)tentados.

    Returns:
        Quantidade traduzida com sucesso nesta chamada. Sucesso é contado
        comparando cada resultado com o texto original, já que traduzir_texto
        devolve o próprio texto original quando a tradução falha após todas
        as tentativas.
    """
    if coluna_pt not in df.columns:
        df[coluna_pt] = None

    ja_traduzido = df[coluna_pt].notna() & (df[coluna_pt] != "") & (df[coluna_pt] != df[coluna_fonte])
    mask = mask_elegivel & ~ja_traduzido

    pulados = int(mask_elegivel.sum() - mask.sum())
    if pulados:
        logger.info("  %d registros de %s já traduzidos anteriormente; pulando.", pulados, coluna_pt)
    if not mask.any():
        return 0

    total = mask.sum()
    logger.info("  Traduzindo %d registros para %s (%d workers)...", total, coluna_pt, _TRANSLATE_MAX_WORKERS)

    valores = df.loc[mask, coluna_fonte].fillna("").tolist()
    with ThreadPoolExecutor(max_workers=_TRANSLATE_MAX_WORKERS) as executor:
        traduzidos = list(executor.map(traduzir_texto, valores))
    df.loc[mask, coluna_pt] = traduzidos

    sucesso = sum(1 for original, traduzido in zip(valores, traduzidos) if original and traduzido != original)
    logger.info("  %d de %d traduzidos com sucesso (%s).", sucesso, total, coluna_pt)

    return sucesso


def _adicionar_traducoes_pt(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Adiciona overview_pt aos registros original_language='en' com overview_en
    preenchido, ainda pendentes (registros com overview_en vazio não têm o que
    traduzir e distorceriam a contagem de sucesso)."""
    if "overview_pt" not in df.columns:
        df["overview_pt"] = None

    mask_en = (
        (df["original_language"] == "en")
        & df["overview_en"].notna()
        & (df["overview_en"] != "")
    )
    if not mask_en.any():
        return df, 0
    sucesso = _traduzir_pendentes(df, "overview_en", "overview_pt", mask_en)
    return df, sucesso


def _adicionar_traducoes_tagline_pt(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Adiciona tagline_pt aos registros com tagline preenchida (qualquer idioma, espelha glue_details)."""
    if "tagline" not in df.columns:
        return df, 0
    mask_elegivel = df["tagline"].notna() & (df["tagline"] != "")
    if not mask_elegivel.any():
        return df, 0
    sucesso = _traduzir_pendentes(df, "tagline", "tagline_pt", mask_elegivel)
    return df, sucesso


def _adicionar_traducoes_keywords_pt(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Adiciona keywords_pt aos registros com keywords preenchidas (TMDB sempre devolve em inglês)."""
    if "keywords" not in df.columns:
        return df, 0
    mask_elegivel = df["keywords"].notna() & (df["keywords"] != "")
    if not mask_elegivel.any():
        return df, 0
    sucesso = _traduzir_pendentes(df, "keywords", "keywords_pt", mask_elegivel)
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
) -> tuple[bool, int]:
    """
    Lê uma partição de year em tb_details_* diretamente do S3, adiciona
    traduções PT e reescreve. Usa S3 em vez de Athena/CTAS para evitar
    permissões athena:GetWorkGroup e glue:DeleteTable.

    Returns:
        Tupla (escreveu, quantidade traduzida com sucesso).
    """
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

    df, sucesso_overview = _adicionar_traducoes_pt(df)
    df, sucesso_tagline = _adicionar_traducoes_tagline_pt(df)
    df, sucesso_keywords = _adicionar_traducoes_keywords_pt(df)
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
