"""
backfill_changes.py — Dispara manualmente o modo changes (TMDB Changes API), sem acionar Lambda nem Glue Details.

Roda a mesma lógica do modo changes (coleta de IDs mudados via `collect_changes_data`, em
app/lambda_api/src/utils.py, e o enriquecimento via `fetch_ids_from_changes_file`/`process_changed_ids`,
em app/glue_details/src/utils.py) diretamente no processo deste script — sem invocar a Lambda API nem
acionar o Glue Details como job. Ambas as partes já são Python puro (TMDB API + boto3/awswrangler); a
única parte que dependia do runtime do Glue (get_parameters_glue/getResolvedOptions) não é usada aqui,
os parâmetros vêm de variáveis de ambiente como em qualquer outro script de scripts/. Mesmo padrão já
usado por scripts/backfill_enriquecimento.py para se tornar independente do Glue Details.

A janela de busca é sempre [domingo passado, sábado de ontem], calculada internamente por
collect_changes_data — este script não aceita nem precisa de datas. Útil para rodar sob demanda quando
o cron semanal falhou ou foi pulado, sem esperar até o próximo domingo.

Uso:
    python scripts/backfill_changes.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DISCOVER_MOVIE
    TABLE_DISCOVER_TV
    TABLE_DETAILS_MOVIE
    TABLE_DETAILS_TV
    TABLE_WATCH_PROVIDERS_MOVIE
    TABLE_WATCH_PROVIDERS_TV
    S3_BUCKET_SOT                  (parquets reais de details/watch_providers)
    S3_BUCKET_TEMP                 (lista de IDs mudados + resultados temporários do Athena)
    TMDB_SECRET_ARN                (ARN do secret com a chave de API do TMDB)
    GLUE_DATA_QUALITY_JOB_NAME     (disparado uma única vez ao final por tabela, ver "Data Quality" abaixo)

Variáveis opcionais:
    TRANSLATE_PROVIDER (padrão: "google")

Data Quality:
    Igual ao padrão de backfill_enriquecimento.py: não dispara por ano — process_changed_ids já
    agrupa todos os anos afetados por content_type num único YEAR separado por vírgula (mesmo
    comportamento de app/glue_details/main.py no modo changes). O disparo em si só acontece UMA VEZ
    ao final, depois de processar movie e tv, e SOMENTE se nenhum dos dois falhou — 4 disparos no
    total (details_movie, details_tv, watch_providers_movie, watch_providers_tv), cada um só se
    houve algum ano afetado. Se movie ou tv falhar, nenhum DQ é disparado, para não validar dado
    possivelmente incompleto.

Retomada automática:
    Diferente da invocação síncrona e curta da Lambda que este script fazia antes, agora ele faz
    chamadas reais de Athena/S3/Secrets Manager/TMDB API no próprio processo — mais exposto a
    ExpiredTokenException/ExpiredToken em runs mais longos (semana com muitos IDs mudados). Se a
    credencial AWS expirar, o script sai com exit code 75 (backfill_shared.RETRYABLE_EXIT_CODE) e o
    workflow renova a credencial e roda o script de novo. Sem checkpoint: só 2 unidades (movie, tv),
    e collect_changes_data/process_changed_ids são idempotentes — refazer do zero é aceitável.
"""

import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app" / "shared_src"))
sys.path.insert(0, str(_REPO_ROOT))
# Import fully-qualified (não "from src.utils import ...") de propósito: cada job Glue tem seu
# próprio pacote "src" (app/<modulo>/src/), e vários scripts/testes desse projeto já contam com o
# nome curto "src.utils" resolvendo para o módulo de SUA própria suite via manipulação de
# sys.path/sys.modules (ver test/conftest.py). Importar com o caminho completo evita colidir com
# esse mecanismo — mesmo racional de scripts/backfill_enriquecimento.py.
from app.glue_details.src.utils import (  # noqa: E402
    fetch_ids_from_changes_file,
    get_api_secret,
    process_changed_ids,
    trigger_glue_job,
)
from app.lambda_api.src.utils import collect_changes_data  # noqa: E402

import backfill_shared as shared  # noqa: E402

logger = shared.setup_logging()


def main() -> None:
    region = shared.require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region

    db_movie = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv    = shared.require_env("GLUE_DATABASE_TV")

    table_discover_movie        = shared.require_env("TABLE_DISCOVER_MOVIE")
    table_discover_tv           = shared.require_env("TABLE_DISCOVER_TV")
    table_details_movie         = shared.require_env("TABLE_DETAILS_MOVIE")
    table_details_tv            = shared.require_env("TABLE_DETAILS_TV")
    table_watch_providers_movie = shared.require_env("TABLE_WATCH_PROVIDERS_MOVIE")
    table_watch_providers_tv    = shared.require_env("TABLE_WATCH_PROVIDERS_TV")

    s3_bucket_sot  = shared.require_env("S3_BUCKET_SOT")
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    secret_arn     = shared.require_env("TMDB_SECRET_ARN")
    dq_job_name    = shared.require_env("GLUE_DATA_QUALITY_JOB_NAME")

    translate_provider = os.environ.get("TRANSLATE_PROVIDER", "google")

    s3_client = boto3.client("s3", region_name=region)

    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_api_secret(secret_arn, "tmdb_api_key")

    content_types = [
        ("movie", db_movie, table_discover_movie, table_details_movie, table_watch_providers_movie),
        ("tv",    db_tv,    table_discover_tv,    table_details_tv,    table_watch_providers_tv),
    ]

    # (table_name, database, affected_years) por tabela — disparo de DQ fica pendente até o fim do
    # loop, e só acontece se nenhum content_type falhar (ver "Data Quality" no docstring).
    dq_pendente: list[tuple[str, str, list[str]]] = []
    failures: list[tuple[str, str]] = []

    for i, (content_type, database, table_discover, table_details, table_watch_providers) in enumerate(
        content_types, start=1,
    ):
        logger.info("[%d/%d] Changes | %s", i, len(content_types), content_type)
        try:
            s3_key = collect_changes_data(api_key, s3_client, s3_bucket_temp, content_type)
            changed_ids = fetch_ids_from_changes_file(f"s3://{s3_bucket_temp}/{s3_key}")
            affected_years = process_changed_ids(
                api_key=api_key,
                database=database,
                table_discover=table_discover,
                table_details=table_details,
                table_watch_providers=table_watch_providers,
                content_type=content_type,
                changed_ids=changed_ids,
                s3_bucket_sot=s3_bucket_sot,
                s3_bucket_temp=s3_bucket_temp,
                translate_provider=translate_provider,
            )
        except ClientError as exc:
            if shared.is_expired_token_error(exc):
                logger.error(
                    "Credenciais AWS expiraram durante o changes de %s. O workflow vai renovar a "
                    "credencial e rodar o script de novo (sem checkpoint — refaz do zero).",
                    content_type,
                )
                raise
            logger.error("Falha ao processar changes de %s: %s.", content_type, exc)
            failures.append((content_type, str(exc)))
        except Exception as exc:  # noqa: BLE001 — falha de um content_type não deve abortar o outro
            logger.error("Falha ao processar changes de %s: %s.", content_type, exc)
            failures.append((content_type, str(exc)))
        else:
            logger.info("Changes de %s concluído com sucesso.", content_type)
            dq_pendente.append((table_details, database, affected_years))
            dq_pendente.append((table_watch_providers, database, affected_years))

    if failures:
        logger.error(
            "%d content_type(s) falharam e precisam ser re-executados: %s",
            len(failures),
            ", ".join(f"{content_type} ({erro})" for content_type, erro in failures),
        )
        return

    logger.info("Changes disparado com sucesso.")

    # Disparo único do Data Quality por tabela, cobrindo todos os anos afetados — mesmo padrão de
    # scripts/backfill_enriquecimento.py (não por ano, e só se não houve falha nenhuma).
    for table_name, database, affected_years in dq_pendente:
        if not affected_years:
            continue
        years_arg = ",".join(affected_years)
        trigger_glue_job(dq_job_name, TABLE_NAME=table_name, DATABASE=database, YEAR=years_arg)


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
