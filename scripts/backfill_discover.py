"""
backfill_discover.py — Popula as tabelas discover de 2000 até o ano atual.

Roda a coleta do TMDB (collect_discover_data, em app/lambda_api/src/utils.py) e a transformação
que hoje roda no Glue ETL para table_type="discover" (read_from_sor/write_parquet_to_sot, em
app/glue_etl/src/utils.py) diretamente no processo deste script, para cada ano/media_type — sem
invocar a Lambda API nem acionar o Glue ETL como job. Ambas as partes já são Python puro (TMDB
API + boto3/awswrangler); a única parte que dependia do runtime do Glue
(get_parameters_glue/getResolvedOptions) não é usada aqui, os parâmetros vêm de variáveis de
ambiente como em qualquer outro script de scripts/. Mesmo padrão já usado por
scripts/backfill_enriquecimento.py, scripts/backfill_changes.py e scripts/backfill_referencias.py.

Não dispara o Glue Details — popular details/watch_providers para o histórico coletado aqui é
responsabilidade de scripts/backfill_enriquecimento.py, rodado à parte (mesma separação já usada
entre scripts/backfill_referencias.py e scripts/backfill_enriquecimento.py). Para popular
referências (genre, configuration, watch_providers_ref) antes de rodar o histórico, use
scripts/backfill_referencias.py.

Uso:
    python scripts/backfill_discover.py

Variáveis de ambiente obrigatórias (copie de infra/terraform.tfvars ou outputs):
    AWS_REGION
    TABLE_GROUP                (identifica o checkpoint; valor "discover" neste script)
    S3_BUCKET_SOR               (JSON bruto coletado do TMDB)
    S3_BUCKET_SOT               (parquets das tabelas discover)
    S3_BUCKET_TEMP              (onde o checkpoint de retomada é armazenado)
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DISCOVER_MOVIE
    TABLE_DISCOVER_TV
    TMDB_SECRET_ARN              (ARN do secret com a chave de API do TMDB)
    GLUE_DATA_QUALITY_JOB_NAME   (disparado uma única vez ao final, ver "Data Quality" abaixo)

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
    WAIT_SECONDS           (padrão: 15 — pausa de cortesia entre unidades para não enviar rajadas
                            consecutivas de requisições ao TMDB; o rate limit em si já é tratado
                            por chamada individual, com retry/backoff, em
                            shared_utils.api_client.api_get)
    TRANSLATE_PROVIDER     (padrão: "google" — discover não traduz nenhum campo; usado só para
                            escolher o serviço primário de detecção de idioma do overview
                            [overview_detected_language], via resolve_detect_language_fn. Se o
                            intervalo de anos cobrir mais de 1 ano, "aws" é rebaixado
                            automaticamente para "google" — ver
                            backfill_shared.apply_translate_cost_guard)

Data Quality:
    Diferente do caminho automático (Glue ETL dispara o Data Quality logo após escrever cada
    tabela), este script dispara o Glue Data Quality (GLUE_DATA_QUALITY_JOB_NAME) UMA VEZ ao
    final de todo o backfill — 2 disparos no total (discover_movie, discover_tv), cobrindo o
    range completo de anos processado (YEAR recebe a lista de anos separada por vírgula — mesmo
    padrão usado por backfill_enriquecimento.py). Só dispara se nenhuma unidade falhou (mesma
    condição que limpa o checkpoint) — se houver falhas, nem o DQ é disparado nem o checkpoint é
    limpo, para não validar um range com dados possivelmente incompletos.

Erros:
    Uma falha numa unidade (coleta ou escrita) é logada e a unidade entra na lista de falhas —
    o backfill segue para a próxima unidade em vez de abortar (mesmo padrão soft-fail-continue de
    backfill_enriquecimento.py).

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken
    do S3), o script sai com exit code 75
    (backfill_shared.RETRYABLE_EXIT_CODE). O workflow renova a credencial
    e roda o script de novo — como o progresso é lido do checkpoint em S3
    (s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{TABLE_GROUP}.json), as
    unidades (ano+tipo) já concluídas com sucesso são puladas. Unidades que
    falharam por outro motivo (não token expirado) não entram no checkpoint —
    continuam sendo re-tentadas em runs futuros com o mesmo range de anos.
"""

import os
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app" / "shared_src"))
sys.path.insert(0, str(_REPO_ROOT))
# Import fully-qualificado (não "from src.utils import ...") de propósito: cada job Glue tem seu
# próprio pacote "src" (app/<modulo>/src/), e vários scripts/testes desse projeto já contam com o
# nome curto "src.utils" resolvendo para o módulo de SUA própria suite via manipulação de
# sys.path/sys.modules (ver test/conftest.py). Importar com o caminho completo evita colidir com
# esse mecanismo — mesmo racional de backfill_enriquecimento.py/backfill_referencias.py.
from app.glue_etl.src.utils import (  # noqa: E402
    detect_language_aws,
    detect_language_langdetect,
    read_from_sor,
    resolve_detect_language_fn,
    trigger_glue_job,
    write_parquet_to_sot,
)
from app.lambda_api.src.utils import collect_discover_data  # noqa: E402
from shared_utils.api_client import get_api_secret  # noqa: E402

import backfill_shared as shared

logger = shared.setup_logging()


def main() -> None:
    region = shared.require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region

    table_group    = shared.require_env("TABLE_GROUP")
    s3_bucket_sor  = shared.require_env("S3_BUCKET_SOR")
    s3_bucket_sot  = shared.require_env("S3_BUCKET_SOT")
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    db_movie       = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv          = shared.require_env("GLUE_DATABASE_TV")

    table_discover_movie = shared.require_env("TABLE_DISCOVER_MOVIE")
    table_discover_tv    = shared.require_env("TABLE_DISCOVER_TV")

    secret_arn  = shared.require_env("TMDB_SECRET_ARN")
    dq_job_name = shared.require_env("GLUE_DATA_QUALITY_JOB_NAME")

    start_year, end_year = shared.read_year_range()
    wait_seconds = int(os.environ.get("WAIT_SECONDS", 15))
    translate_provider = shared.apply_translate_cost_guard(
        os.environ.get("TRANSLATE_PROVIDER", "google"), start_year, end_year,
    )
    detect_fn = resolve_detect_language_fn(
        detect_language_langdetect, detect_language_aws, provider=translate_provider,
    )

    s3_client = boto3.client("s3", region_name=region)

    years = list(range(start_year, end_year + 1))
    total_units = len(years) * 2
    logger.info(
        "Backfill de discover: %d anos (%d-%d) x 2 tipos = %d unidades",
        len(years), start_year, end_year, total_units,
    )

    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_api_secret(secret_arn, "tmdb_api_key")

    completed = shared.load_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year)

    unidades = [
        (media_type, year, database)
        for year in years
        for media_type, database in [("movie", db_movie), ("tv", db_tv)]
    ]
    pendentes = [u for u in unidades if f"{u[0]}:{u[1]}" not in completed]
    shared.log_resume_progress(logger, "unidades já concluídas", len(unidades), len(pendentes))

    failures: list[tuple[str, int, str]] = []
    for i, (media_type, year, database) in enumerate(pendentes, start=1):
        logger.info("[%d/%d] Discover | %s | year=%d", i, len(pendentes), media_type, year)

        table_discover = table_discover_movie if media_type == "movie" else table_discover_tv

        try:
            collect_discover_data(
                api_key=api_key,
                s3_client=s3_client,
                bucket=s3_bucket_sor,
                content_type=media_type,
                folder=f"tmdb/discover/{media_type}",
                year=year,
            )
            df = read_from_sor(
                s3_bucket_sor, media_type, "discover", str(year), detect_fn=detect_fn,
            )
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot=s3_bucket_sot,
                table_name=table_discover,
                database=database,
                partition_cols=["year"],
                mode="overwrite_partitions",
            )
        except ClientError as exc:
            if shared.is_expired_token_error(exc):
                logger.error(
                    "Credenciais AWS expiraram durante o discover de %s year=%d. O workflow "
                    "vai renovar a credencial e retomar do checkpoint automaticamente "
                    "(ver scripts/backfill_shared.py).",
                    media_type, year,
                )
                raise
            logger.error(
                "Falha ao processar discover %s year=%d: %s. Continuando com o próximo...",
                media_type, year, exc,
            )
            failures.append((media_type, year, str(exc)))
        except Exception as exc:  # noqa: BLE001 — falha de uma unidade não deve abortar o backfill inteiro
            logger.error(
                "Falha ao processar discover %s year=%d: %s. Continuando com o próximo...",
                media_type, year, exc,
            )
            failures.append((media_type, year, str(exc)))
        else:
            logger.info("Discover concluído com sucesso para %s year=%d.", media_type, year)
            completed.add(f"{media_type}:{year}")
            shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)

        if i < len(pendentes) and wait_seconds > 0:
            time.sleep(wait_seconds)

    logger.info("Backfill de discover concluído: %d unidades processadas.", len(pendentes))
    if failures:
        logger.error(
            "%d unidade(s) falharam e precisam ser re-executadas: %s",
            len(failures),
            ", ".join(f"{media_type}/{year} ({erro})" for media_type, year, erro in failures),
        )
    else:
        # Disparo único do Data Quality cobrindo todo o range processado, em vez de por unidade —
        # mesmo padrão de backfill_enriquecimento.py (YEAR aceita lista de anos separada por vírgula).
        years_arg = ",".join(str(year) for year in years)
        logger.info(
            "Disparando Glue Data Quality uma única vez (YEAR=%s) para as 2 tabelas...", years_arg,
        )
        for table_name, database in (
            (table_discover_movie, db_movie),
            (table_discover_tv, db_tv),
        ):
            trigger_glue_job(dq_job_name, TABLE_NAME=table_name, DATABASE=database, YEAR=years_arg)
            time.sleep(5)
        shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
