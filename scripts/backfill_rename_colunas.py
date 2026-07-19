"""
backfill_rename_colunas.py — Migra dt_processamento/dt_atualizacao (nomes de coluna
legados em português, pré-rename para inglês — ver CLAUDE.md e infra/glue_catalog.tf)
para processed_date/updated_date nas partições já gravadas no S3.

Não chama a API do TMDB — apenas reescreve o Parquet já existente. Motivo: depois
que o Terraform aplica o rename no Glue Catalog, o pipeline normal (Glue Details)
só repopula processed_date/updated_date para IDs que ainda aparecem no discover
atual. IDs que saíram do discover ao longo do tempo (o discover reconstrói a
partição do zero a cada run; details/watch_providers acumulam histórico desde
2000) nunca mais entram no delta reprocessado — ficariam com a coluna nova
permanentemente nula. Este script cobre 100% dos casos, incluindo esses,
lendo o schema físico real de cada partição (bypassa o Glue Catalog) e usando
o valor já gravado sob o nome antigo quando o novo ainda não existe.

Para cada (tabela, year) das tabelas de details e watch_providers:
  1. Lê a partição diretamente do S3 (schema físico real — pode ter as duas
     colunas coexistindo, se a partição já foi parcialmente reprocessada pelo
     pipeline normal depois do rename).
  2. Preenche a coluna nova com o valor já existente nela; onde estiver nula,
     usa o valor da coluna antiga (coalesce).
  3. Descarta a coluna antiga e regrava com mode="overwrite_partitions".
  4. Partição sem a coluna antiga (já migrada) ou sem dados é pulada sem escrita.

Pré-requisito: terraform apply já aplicado com os novos nomes de coluna no Glue
Catalog (ver infra/glue_catalog.tf) — senão o Athena não reconhece
processed_date/updated_date nas consultas que dependem deles.

Uso:
    python scripts/backfill_rename_colunas.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    TABLE_GROUP                    (identifica o checkpoint; valor "rename_colunas" neste script)
    S3_BUCKET_SOT                  (parquets reais de details/watch_providers)
    S3_BUCKET_TEMP                 (onde o checkpoint de retomada é armazenado)
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DETAILS_MOVIE
    TABLE_DETAILS_TV
    TABLE_WATCH_PROVIDERS_MOVIE
    TABLE_WATCH_PROVIDERS_TV

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken
    do S3), o script sai com exit code 75 (backfill_shared.RETRYABLE_EXIT_CODE).
    O workflow renova a credencial e roda o script de novo — como o progresso é
    lido do checkpoint em S3 (s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/
    {TABLE_GROUP}.json), as partições (tabela+ano) já concluídas são puladas.
"""

import os

import awswrangler as wr
import boto3
from botocore.exceptions import ClientError

import backfill_shared as shared

logger = shared.setup_logging()


def _rename_partition_column(
    database: str,
    table_name: str,
    year: str,
    s3_bucket_sot: str,
    old_column: str,
    new_column: str,
) -> bool:
    """
    Migra old_column para new_column em uma partição year, lida direto do S3.

    Args:
        database:      Nome do banco de dados no Glue Catalog.
        table_name:    Nome da tabela (details ou watch_providers, movie ou tv).
        year:          Partição a migrar.
        s3_bucket_sot: Nome do bucket SOT onde os dados estão gravados.
        old_column:    Nome antigo (em português) da coluna.
        new_column:    Nome novo (em inglês) da coluna.

    Returns:
        True se a partição foi regravada, False se não havia nada a migrar
        (sem arquivos, partição vazia, ou já totalmente migrada).
    """
    s3_path_year = f"s3://{s3_bucket_sot}/tmdb/{table_name}/year={year}/"
    try:
        df = wr.s3.read_parquet(path=s3_path_year)
    except ClientError as exc:
        shared.log_expired_token(exc, f"leitura de {s3_path_year}")
        raise
    except Exception as exc:
        if "NoFilesFound" in type(exc).__name__ or "NoFilesFound" in str(exc):
            logger.info("  Nenhum arquivo em %s. Pulando.", s3_path_year)
            return False
        raise

    if df.empty:
        logger.info("  Nenhum registro para year=%s em '%s'. Pulando.", year, table_name)
        return False

    if old_column not in df.columns:
        logger.info(
            "  '%s' já migrada para year=%s em '%s' (sem '%s' no schema físico). Pulando.",
            new_column, year, table_name, old_column,
        )
        return False

    if new_column not in df.columns:
        df[new_column] = None
    migrados = df[new_column].isna().sum()
    df[new_column] = df[new_column].fillna(df[old_column])
    df = df.drop(columns=[old_column])
    ainda_nulos = df[new_column].isna().sum()
    if ainda_nulos:
        logger.warning(
            "  year=%s em '%s': %d registro(s) continuam sem '%s' após o merge "
            "(nem coluna nova nem antiga preenchidas) — investigar.",
            year, table_name, ainda_nulos, new_column,
        )

    df["year"] = year
    s3_path = f"s3://{s3_bucket_sot}/tmdb/{table_name}/"
    try:
        wr.s3.to_parquet(
            df=df,
            path=s3_path,
            dataset=True,
            partition_cols=["year"],
            mode="overwrite_partitions",
            database=database,
            table=table_name,
        )
    except ClientError as exc:
        shared.log_expired_token(exc, f"escrita de {s3_path} (year={year})")
        raise
    logger.info(
        "  year=%s em '%s': %d registro(s) migrado(s) de '%s' para '%s' (%d regravado(s) no total).",
        year, table_name, migrados, old_column, new_column, len(df),
    )
    return True


def main() -> None:
    region = shared.require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region

    table_group    = shared.require_env("TABLE_GROUP")
    s3_bucket_sot  = shared.require_env("S3_BUCKET_SOT")
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    db_movie       = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv          = shared.require_env("GLUE_DATABASE_TV")

    table_details_movie         = shared.require_env("TABLE_DETAILS_MOVIE")
    table_details_tv            = shared.require_env("TABLE_DETAILS_TV")
    table_watch_providers_movie = shared.require_env("TABLE_WATCH_PROVIDERS_MOVIE")
    table_watch_providers_tv    = shared.require_env("TABLE_WATCH_PROVIDERS_TV")

    start_year, end_year = shared.read_year_range(end_env="BACKFILL_END_YEAR")

    # (database, tabela, coluna antiga, coluna nova)
    tabelas = [
        (db_movie, table_details_movie,         "dt_processamento", "processed_date"),
        (db_tv,    table_details_tv,             "dt_processamento", "processed_date"),
        (db_movie, table_watch_providers_movie,  "dt_atualizacao",   "updated_date"),
        (db_tv,    table_watch_providers_tv,     "dt_atualizacao",   "updated_date"),
    ]

    years = list(range(start_year, end_year + 1))
    total = len(years) * len(tabelas)
    logger.info(
        "Backfill de rename de colunas: %d até %d | %d partições (%d tabelas x %d ano(s))",
        start_year, end_year, total, len(tabelas), len(years),
    )
    s3_client = boto3.client("s3", region_name=region)

    completed = shared.load_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year)

    units = [
        (database, table_name, year, old_column, new_column)
        for year in years
        for database, table_name, old_column, new_column in tabelas
    ]
    pending = [u for u in units if f"{u[1]}:{u[2]}" not in completed]
    shared.log_resume_progress(logger, "partições já concluídas", len(units), len(pending))

    migradas = 0
    for i, (database, table_name, year, old_column, new_column) in enumerate(pending, start=1):
        logger.info("[%d/%d] %s | year=%d", i, len(pending), table_name, year)
        if _rename_partition_column(
            database=database,
            table_name=table_name,
            year=str(year),
            s3_bucket_sot=s3_bucket_sot,
            old_column=old_column,
            new_column=new_column,
        ):
            migradas += 1
        completed.add(f"{table_name}:{year}")
        shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)

    shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)
    logger.info(
        "Backfill de rename de colunas concluído: %d até %d | %d de %d partições regravadas.",
        start_year, end_year, migradas, total,
    )


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
