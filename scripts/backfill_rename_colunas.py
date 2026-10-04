"""
backfill_rename_colunas.py — Renomeia colunas nas partições já gravadas no S3, para
acompanhar o rename aplicado no Glue Catalog pelo Terraform (infra/glue_catalog.tf):

  - watch_providers movie/tv: updated_date → processed_date (padroniza o nome da coluna de
    processamento com as demais tabelas — mesmo tipo `date`, mesma posição).
  - discover movie/tv: overview_detected_language → overview_detected_language_pt e
    overview_translated_pt_br → overview_translated_pt (padroniza o sufixo de idioma com o
    par _en/_pt de details e configuration).

Não chama a API do TMDB — apenas reescreve o Parquet já existente. Motivo: depois
que o Terraform aplica o rename no Glue Catalog, o pipeline normal só repopula a
coluna nova para IDs que ainda são reprocessados (watch_providers acumula histórico
desde 2000 e o discover só reconstrói o ano corrente). As demais partições ficariam com
a coluna nova permanentemente nula — e, no discover, overview_detected_language_pt nulo
faz o gate do AGG (= 'pt') descartar o overview e esvazia o cache de idioma do glue_etl
(o LLM redetectaria tudo). Este script cobre 100% dos casos, lendo o schema físico real
de cada partição (bypassa o Glue Catalog) e usando o valor já gravado sob o nome antigo
quando o novo ainda não existe.

Para cada (tabela, year):
  1. Lê a partição diretamente do S3 (schema físico real — pode ter as duas
     colunas coexistindo, se a partição já foi parcialmente reprocessada pelo
     pipeline normal depois do rename).
  2. Para cada coluna antiga presente, preenche a coluna nova com o valor já existente
     nela; onde estiver nula, usa o valor da coluna antiga (coalesce). Várias colunas da
     mesma tabela são renomeadas numa única leitura/regravação.
  3. Descarta as colunas antigas e regrava com mode="overwrite_partitions".
  4. Partição sem nenhuma coluna antiga (já migrada) ou sem dados é pulada sem escrita.

A tabela de data quality NÃO passa por aqui: a coluna datetime_process (timestamp) virou
processed_date (date) e, como o overwrite_partitions por source_table/year mantém só a
última avaliação, a migração é rodar scripts/backfill_data_quality.py.

Pré-requisito: terraform apply já aplicado com os novos nomes de coluna no Glue
Catalog (ver infra/glue_catalog.tf) — senão o Athena não reconhece os nomes novos.
Rodar logo após o deploy do código, antes do próximo AGG agendado.

Uso:
    python scripts/backfill_rename_colunas.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    TABLE_GROUP                    (identifica o checkpoint; valor "rename_colunas" neste script)
    S3_BUCKET_SOT                  (parquets reais de discover/watch_providers)
    S3_BUCKET_TEMP                 (onde o checkpoint de retomada é armazenado)
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DISCOVER_MOVIE
    TABLE_DISCOVER_TV
    TABLE_WATCH_PROVIDERS_MOVIE
    TABLE_WATCH_PROVIDERS_TV
    GLUE_DATA_QUALITY_JOB_NAME (usada pela chamada local ao Glue AGG ao final, ver "Glue AGG" abaixo)
    S3_BUCKET_SPEC, S3_PREFIX_SPEC, DB_UNIFIED, TABLE_DISCOVER_UNIFIED, ENVIRONMENT
                                (idem, ver "Glue AGG" abaixo)

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)

Glue AGG:
    Ao final, antes de limpar o checkpoint, roda o Glue AGG (query Athena de unificação +
    escrita da tabela SPEC + disparo do Data Quality sobre a tabela unificada) diretamente no
    processo — ver backfill_shared.trigger_agg_locally. Faz sentido rodar aqui em particular: a
    query de unificação do AGG usa overview_detected_language_pt (app/glue_agg/src/queries.py)
    como gate do overview do discover — coluna que só existe nas partições antigas depois
    deste rename. Uma falha nessa etapa é logada como ERROR mas
    não derruba o backfill (que já terminou com sucesso) — o trigger agendado (sábado/domingo
    08:00 BRT) e o alarme SNS de falha continuam cobrindo o caso.

Notificação:
    Ao final, publica no tópico SNS de sucesso do backfill (SNS_TOPIC_ARN_BACKFILL_SUCCESS,
    opcional) — ver backfill_shared.notify_backfill_success.

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


def _rename_partition_columns(
    database: str,
    table_name: str,
    year: str,
    s3_bucket_sot: str,
    renames: dict[str, str],
) -> bool:
    """
    Migra colunas antigas para as novas em uma partição year, lida direto do S3.

    Args:
        database:      Nome do banco de dados no Glue Catalog.
        table_name:    Nome da tabela (discover ou watch_providers, movie ou tv).
        year:          Partição a migrar.
        s3_bucket_sot: Nome do bucket SOT onde os dados estão gravados.
        renames:       Mapa nome antigo → nome novo das colunas a renomear.

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

    pendentes = {old: new for old, new in renames.items() if old in df.columns}
    if not pendentes:
        logger.info(
            "  Colunas %s já migradas para year=%s em '%s' (sem as antigas no schema físico). Pulando.",
            list(renames.values()), year, table_name,
        )
        return False

    for old_column, new_column in pendentes.items():
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
        logger.info(
            "  year=%s em '%s': %d registro(s) migrado(s) de '%s' para '%s'.",
            year, table_name, migrados, old_column, new_column,
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
    logger.info("  year=%s em '%s': %d registro(s) regravado(s).", year, table_name, len(df))
    return True


def main() -> None:
    region = shared.require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region

    table_group    = shared.require_env("TABLE_GROUP")
    s3_bucket_sot  = shared.require_env("S3_BUCKET_SOT")
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    db_movie       = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv          = shared.require_env("GLUE_DATABASE_TV")

    table_discover_movie        = shared.require_env("TABLE_DISCOVER_MOVIE")
    table_discover_tv           = shared.require_env("TABLE_DISCOVER_TV")
    table_watch_providers_movie = shared.require_env("TABLE_WATCH_PROVIDERS_MOVIE")
    table_watch_providers_tv    = shared.require_env("TABLE_WATCH_PROVIDERS_TV")
    dq_job_name                 = shared.require_env("GLUE_DATA_QUALITY_JOB_NAME")

    start_year, end_year = shared.read_year_range(end_env="BACKFILL_END_YEAR")

    discover_renames = {
        "overview_detected_language": "overview_detected_language_pt",
        "overview_translated_pt_br":  "overview_translated_pt",
    }
    watch_providers_renames = {"updated_date": "processed_date"}

    # (database, tabela, {coluna antiga: coluna nova})
    tabelas = [
        (db_movie, table_discover_movie,         discover_renames),
        (db_tv,    table_discover_tv,            discover_renames),
        (db_movie, table_watch_providers_movie,  watch_providers_renames),
        (db_tv,    table_watch_providers_tv,     watch_providers_renames),
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
        (database, table_name, year, renames)
        for year in years
        for database, table_name, renames in tabelas
    ]
    pending = [u for u in units if f"{u[1]}:{u[2]}" not in completed]
    shared.log_resume_progress(logger, "partições já concluídas", len(units), len(pending))

    migradas = 0
    for i, (database, table_name, year, renames) in enumerate(pending, start=1):
        logger.info("[%d/%d] %s | year=%d", i, len(pending), table_name, year)
        if _rename_partition_columns(
            database=database,
            table_name=table_name,
            year=str(year),
            s3_bucket_sot=s3_bucket_sot,
            renames=renames,
        ):
            migradas += 1
        completed.add(f"{table_name}:{year}")
        shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)

    shared.trigger_agg_locally(
        s3_bucket_spec=shared.require_env("S3_BUCKET_SPEC"),
        s3_prefix_spec=shared.require_env("S3_PREFIX_SPEC"),
        s3_bucket_temp=s3_bucket_temp,
        db_movie=db_movie,
        db_tv=db_tv,
        db_unified=shared.require_env("DB_UNIFIED"),
        table_name=shared.require_env("TABLE_DISCOVER_UNIFIED"),
        dq_job_name=dq_job_name,
        environment=shared.require_env("ENVIRONMENT"),
    )
    shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)
    summary = (
        f"Backfill de rename de colunas concluído: {start_year} até {end_year} | "
        f"{migradas} de {total} partições regravadas."
    )
    logger.info(summary)
    shared.notify_backfill_success(table_group, summary)


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
