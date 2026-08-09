"""
backfill_referencias.py — Atualiza tabelas de referência (genre, configuration, watch_providers_ref).

Roda a coleta do TMDB (collect_genre_data/collect_configuration_data/collect_watch_providers_ref,
em app/lambda_api/src/utils.py) e a transformação que hoje roda no Glue ETL para esses 3
TABLE_TYPE (read_from_sor/write_parquet_to_sot, em app/glue_etl/src/utils.py) diretamente no
processo deste script — sem invocar a Lambda API nem acionar o Glue ETL como job. Ambas as
partes já são Python puro (TMDB API + boto3/awswrangler); a única parte que dependia do runtime
do Glue (get_parameters_glue/getResolvedOptions) não é usada aqui, os parâmetros vêm de
variáveis de ambiente como em qualquer outro script de scripts/. Mesmo padrão já usado por
scripts/backfill_enriquecimento.py e scripts/backfill_changes.py para se tornarem independentes
do Glue Details.

Não depende de ano (mesmo comportamento de sempre — genre/configuration/watch_providers_ref não
são particionados por ano).

Uso:
    python scripts/backfill_referencias.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    S3_BUCKET_SOR                  (JSON bruto coletado do TMDB)
    S3_BUCKET_SOT                  (parquets reais das 6 tabelas de referência)
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_GENRE_MOVIE
    TABLE_GENRE_TV
    TABLE_CONFIGURATION_LANGUAGES
    TABLE_CONFIGURATION_COUNTRIES
    TABLE_WATCH_PROVIDERS_REF_MOVIE
    TABLE_WATCH_PROVIDERS_REF_TV
    TMDB_SECRET_ARN                 (ARN do secret com a chave de API do TMDB)
    GLUE_DATA_QUALITY_JOB_NAME      (disparado uma vez por tabela gravada, ver "Data Quality" abaixo)
    S3_BUCKET_TEMP                  (área de resultados temporários do Athena usada pelo Glue AGG)
    S3_BUCKET_SPEC, S3_PREFIX_SPEC, DB_UNIFIED, TABLE_DISCOVER_UNIFIED, ENVIRONMENT
                                     (usadas pela chamada local ao Glue AGG, ver "Glue AGG" abaixo)

Variáveis opcionais:
    TRANSLATE_PROVIDER (padrão: "google" — usado só por "configuration", que traduz
                        english_name para name_pt; resolvido uma vez por content_type, mesmo
                        padrão de backfill_enriquecimento.py/backfill_changes.py, para que a
                        primeira content_type processada não esgote sozinha o orçamento de
                        fallback ao AWS Translate)

Data Quality:
    Diferente do caminho automático (Glue ETL dispara o Data Quality logo após escrever cada
    tabela), este script segue o mesmo padrão: dispara o Glue Data Quality uma vez por tabela
    gravada com sucesso, imediatamente após a escrita — 6 disparos no total (genre_movie,
    genre_tv, configuration_languages, configuration_countries, watch_providers_ref_movie,
    watch_providers_ref_tv), exceto se watch_providers_ref falhar com HTTPError (ver "Erros"
    abaixo), caso em que esse disparo específico é pulado.

Glue AGG:
    Ao final, se o script chegou até o fim sem exceção não tratada, roda o Glue AGG (query
    Athena de unificação + escrita da tabela SPEC + disparo do Data Quality sobre a tabela
    unificada) diretamente no processo — ver backfill_shared.trigger_agg_locally. Uma falha
    nessa etapa é logada como ERROR mas não derruba o backfill (que já terminou com sucesso) —
    o trigger agendado (sábado/domingo 08:00 BRT) e o alarme SNS de falha continuam cobrindo o
    caso.

Notificação:
    Ao final, publica no tópico SNS de sucesso do backfill (SNS_TOPIC_ARN_BACKFILL_SUCCESS,
    opcional) — ver backfill_shared.notify_backfill_success. Uma falha em genre/configuration
    aborta o script antes desse ponto (ver "Erros" abaixo), então não há notificação nesse caso.

Erros:
    genre e configuration: uma falha propaga e aborta o script (mesmo comportamento de sempre —
    antes, uma falha na Lambda abortava antes da segunda invocação; agora, uma falha em
    qualquer coleta/escrita aborta antes da próxima). watch_providers_ref: HTTPError é
    capturado, logado e ignorado — dados anteriores no S3 continuam válidos (mesmo tratamento
    já existente em app/lambda_api/main.py).

Retomada automática:
    Não grava checkpoint (só 6 unidades, sem dependência de ano). Se a credencial AWS expirar
    (ExpiredTokenException do STS ou ExpiredToken do S3/Secrets Manager), o script sai com exit
    code 75 (backfill_shared.RETRYABLE_EXIT_CODE) e o workflow renova a credencial e roda o
    script de novo — como não há checkpoint, a próxima tentativa refaz tudo do zero.
"""

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import boto3
from requests.exceptions import HTTPError

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app" / "shared_src"))
sys.path.insert(0, str(_REPO_ROOT))
# Import fully-qualified (não "from src.utils import ...") de propósito: cada job Glue tem seu
# próprio pacote "src" (app/<modulo>/src/), e vários scripts/testes desse projeto já contam com o
# nome curto "src.utils" resolvendo para o módulo de SUA própria suite via manipulação de
# sys.path/sys.modules (ver test/conftest.py). Importar com o caminho completo evita colidir com
# esse mecanismo — mesmo racional de scripts/backfill_enriquecimento.py e backfill_changes.py.
import backfill_shared as shared  # noqa: E402
from shared_utils.api_client import get_api_secret  # noqa: E402

from app.glue_etl.src.utils import (  # noqa: E402
    detect_language_aws,
    detect_language_langdetect,
    read_from_sor,
    resolve_detect_language_fn,
    resolve_translate_fn,
    translate_text,
    translate_text_aws,
    trigger_glue_job,
    write_parquet_to_sot,
)
from app.lambda_api.src.utils import (  # noqa: E402
    collect_configuration_data,
    collect_genre_data,
    collect_watch_providers_ref,
)

logger = shared.setup_logging()


def _write_table(
    *,
    media_type: str,
    table_type: str,
    table_name: str,
    database: str,
    s3_bucket_sor: str,
    s3_bucket_sot: str,
    dq_job_name: str,
    translate_fn: Callable[[str], str] | None = None,
    detect_fn: Callable[[str], str | None] | None = None,
) -> None:
    """Lê table_type do SOR, grava Parquet no SOT e dispara o Glue Data Quality.

    Réplica direta do que app/glue_etl/main.py faz para TABLE_TYPE in
    (genre, configuration, watch_providers_ref): nenhuma delas é particionada por ano
    (partition_cols=None, mode="overwrite" — mesma entrada de _TABLE_CONFIG em glue_etl/main.py).
    """
    df = read_from_sor(
        s3_bucket_sor,
        media_type,
        table_type,
        translate_fn=translate_fn,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_name,
        detect_fn=detect_fn,
    )
    write_parquet_to_sot(
        df=df,
        s3_bucket_sot=s3_bucket_sot,
        table_name=table_name,
        database=database,
        partition_cols=None,
        mode="overwrite",
    )
    trigger_glue_job(dq_job_name, TABLE_NAME=table_name, DATABASE=database)


def _process_content_type(
    *,
    media_type: str,
    api_key: str,
    s3_client: Any,
    database: str,
    table_genre: str,
    table_configuration: str,
    table_watch_providers_ref: str,
    s3_bucket_sor: str,
    s3_bucket_sot: str,
    dq_job_name: str,
    translate_provider: str,
) -> None:
    logger.info("Coletando gêneros do TMDB para '%s'...", media_type)
    collect_genre_data(api_key, s3_client, s3_bucket_sor, media_type)
    _write_table(
        media_type=media_type,
        table_type="genre",
        table_name=table_genre,
        database=database,
        s3_bucket_sor=s3_bucket_sor,
        s3_bucket_sot=s3_bucket_sot,
        dq_job_name=dq_job_name,
    )

    # Resolvidos uma vez por content_type (não uma vez só para o script inteiro), mesmo padrão
    # de backfill_enriquecimento.py/backfill_changes.py — evita que a primeira content_type
    # esgote sozinha o orçamento de fallback ao AWS Translate.
    translate_fn = resolve_translate_fn(translate_provider, translate_text, translate_text_aws)
    detect_fn = resolve_detect_language_fn(
        detect_language_langdetect, detect_language_aws, provider=translate_provider,
    )

    logger.info("Coletando configurações do TMDB para '%s'...", media_type)
    collect_configuration_data(api_key, s3_client, s3_bucket_sor, media_type)
    _write_table(
        media_type=media_type,
        table_type="configuration",
        table_name=table_configuration,
        database=database,
        s3_bucket_sor=s3_bucket_sor,
        s3_bucket_sot=s3_bucket_sot,
        dq_job_name=dq_job_name,
        translate_fn=translate_fn,
        detect_fn=detect_fn,
    )

    logger.info("Coletando referência de watch providers do TMDB para '%s'...", media_type)
    try:
        collect_watch_providers_ref(api_key, s3_client, s3_bucket_sor, media_type)
    except HTTPError:
        logger.error(
            "Falha ao coletar watch_providers_ref para '%s'. Pulando — dados anteriores no "
            "S3 permanecem válidos.", media_type,
        )
        return

    _write_table(
        media_type=media_type,
        table_type="watch_providers_ref",
        table_name=table_watch_providers_ref,
        database=database,
        s3_bucket_sor=s3_bucket_sor,
        s3_bucket_sot=s3_bucket_sot,
        dq_job_name=dq_job_name,
    )


def main() -> None:
    region = shared.require_env("AWS_REGION")

    s3_bucket_sor  = shared.require_env("S3_BUCKET_SOR")
    s3_bucket_sot  = shared.require_env("S3_BUCKET_SOT")
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    db_movie       = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv          = shared.require_env("GLUE_DATABASE_TV")

    table_genre_movie               = shared.require_env("TABLE_GENRE_MOVIE")
    table_genre_tv                  = shared.require_env("TABLE_GENRE_TV")
    table_configuration_languages   = shared.require_env("TABLE_CONFIGURATION_LANGUAGES")
    table_configuration_countries   = shared.require_env("TABLE_CONFIGURATION_COUNTRIES")
    table_watch_providers_ref_movie = shared.require_env("TABLE_WATCH_PROVIDERS_REF_MOVIE")
    table_watch_providers_ref_tv    = shared.require_env("TABLE_WATCH_PROVIDERS_REF_TV")

    secret_arn  = shared.require_env("TMDB_SECRET_ARN")
    dq_job_name = shared.require_env("GLUE_DATA_QUALITY_JOB_NAME")

    translate_provider = os.environ.get("TRANSLATE_PROVIDER", "google")

    s3_client = boto3.client("s3", region_name=region)

    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_api_secret(secret_arn, "tmdb_api_key")

    content_types = [
        ("movie", db_movie, table_genre_movie, table_configuration_languages, table_watch_providers_ref_movie),
        ("tv",    db_tv,    table_genre_tv,    table_configuration_countries, table_watch_providers_ref_tv),
    ]

    logger.info("Atualizando referências (genre, configuration, watch_providers_ref) — movie e tv")

    for i, (media_type, database, table_genre, table_configuration, table_watch_providers_ref) in enumerate(
        content_types, start=1,
    ):
        logger.info("[%d/%d] Referências | %s", i, len(content_types), media_type)
        _process_content_type(
            media_type=media_type,
            api_key=api_key,
            s3_client=s3_client,
            database=database,
            table_genre=table_genre,
            table_configuration=table_configuration,
            table_watch_providers_ref=table_watch_providers_ref,
            s3_bucket_sor=s3_bucket_sor,
            s3_bucket_sot=s3_bucket_sot,
            dq_job_name=dq_job_name,
            translate_provider=translate_provider,
        )

    logger.info("Referências atualizadas.")

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
    shared.notify_backfill_success(
        "referencias",
        "Backfill de referências concluído: genre, configuration e watch_providers_ref "
        "atualizadas (movie e tv), Data Quality e Glue AGG disparados.",
    )


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
