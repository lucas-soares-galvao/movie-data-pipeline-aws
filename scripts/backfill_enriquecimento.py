"""
backfill_enriquecimento.py — Re-busca detalhes com campos enriquecidos (elenco, diretor, keywords, etc.)

Roda a lógica de enriquecimento (app/glue_details/src/utils.py, função
run_details_and_watch_providers_for_year) diretamente no processo deste script, para cada
ano/media_type — sem acionar o Glue Details como job Glue. A lógica de negócio é Python puro
(TMDB API + awswrangler); a única parte que dependia do runtime do Glue
(get_parameters_glue/getResolvedOptions) não é usada aqui, os parâmetros vêm de variáveis de
ambiente como em qualquer outro script de scripts/. Isso elimina o custo de Glue Job deste
backfill — o Glue Data Quality continua sendo acionado, mas uma única vez ao final de todo o
backfill (não mais 2x por unidade), ver "Data Quality" abaixo.

Aproveitando que o delta mensal (processed_date >= date_trunc('month', current_date)) considera
IDs de meses anteriores como stale, todos os IDs serão re-buscados com os novos campos do
append_to_response (credits, keywords, release_dates, videos, external_ids).

Pré-requisitos:
  1. Terraform apply já executado com os novos schemas no Glue Catalog e com as permissões
     IAM de Athena/Secrets Manager/Glue Catalog na role de backfill (ver infra/iam_backfill.tf)
  2. Rodar preferencialmente no início do mês (quando NENHUM ID tem processed_date no mês atual)

Uso:
    python scripts/backfill_enriquecimento.py

Variáveis de ambiente obrigatórias:
    AWS_REGION
    TABLE_GROUP                   (identifica o checkpoint; valor "detalhes_e_providers" neste script)
    S3_BUCKET_SOT                 (parquets reais de details/watch_providers)
    S3_BUCKET_TEMP                (checkpoint de retomada + resultados temporários do Athena)
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV
    TABLE_DISCOVER_MOVIE
    TABLE_DISCOVER_TV
    TABLE_DETAILS_MOVIE
    TABLE_DETAILS_TV
    TABLE_WATCH_PROVIDERS_MOVIE
    TABLE_WATCH_PROVIDERS_TV
    TMDB_SECRET_ARN                (ARN do secret com a chave de API do TMDB)
    GLUE_DATA_QUALITY_JOB_NAME     (disparado uma única vez ao final, ver "Data Quality" abaixo)
    S3_BUCKET_SPEC, S3_PREFIX_SPEC, DB_UNIFIED, TABLE_DISCOVER_UNIFIED, ENVIRONMENT
                                   (usadas pela chamada local ao Glue AGG, ver "Glue AGG" abaixo)

Variáveis opcionais:
    BACKFILL_START_YEAR   (padrão: 2000)
    BACKFILL_END_YEAR     (padrão: ano atual)
    WAIT_SECONDS          (padrão: 15 — pausa de cortesia entre unidades para não enviar rajadas
                           consecutivas de requisições ao TMDB; o rate limit em si já é tratado
                           por chamada individual, com retry/backoff, em
                           shared_utils.api_client.api_get)
    FORCE_REFETCH         (padrão: true — quando true, ignora delta mensal e re-busca todos os IDs)
    TRANSLATE_PROVIDER    (padrão: "google" — grátis; volume alto por re-enriquecer o histórico
                           inteiro. "aws" usa AWS Translate, útil para testar um período menor
                           via BACKFILL_START_YEAR/BACKFILL_END_YEAR — se o intervalo cobrir
                           mais de 1 ano, é rebaixado automaticamente para "google" (proteção
                           de custo, ver backfill_shared.apply_translate_cost_guard). O serviço
                           não escolhido é usado como fallback automático, capado por
                           caracteres quando é o AWS — ver shared_utils.traducao.resolve_translate_fn)

Data Quality:
    Diferente do caminho automático (Glue Details dispara o Data Quality 2x por unidade), este
    script só dispara o Glue Data Quality (GLUE_DATA_QUALITY_JOB_NAME) UMA VEZ ao final de todo o
    backfill — 4 disparos no total (details_movie, details_tv, watch_providers_movie,
    watch_providers_tv), cobrindo o range completo de anos processado (YEAR recebe a lista de
    anos separada por vírgula — mesmo padrão já usado pelo modo "changes" de
    app/glue_details/main.py). Só dispara se nenhuma unidade falhou (mesma condição que hoje
    limpa o checkpoint) — se houver falhas, nem o DQ é disparado nem o checkpoint é limpo, para
    não validar um range com dados possivelmente incompletos.

Glue AGG:
    Se nenhuma unidade falhou, roda o Glue AGG (query Athena de unificação + escrita da tabela
    SPEC + disparo do Data Quality sobre a tabela unificada) diretamente no processo, uma única
    vez, logo antes de limpar o checkpoint — ver backfill_shared.trigger_agg_locally. main()
    aceita trigger_agg=False para suprimir esse disparo quando chamado por
    backfill_historico.py (que dispara o AGG ele mesmo, uma única vez, depois dos dois estágios
    que encadeia). Uma falha nessa etapa é logada como ERROR mas não derruba o backfill (que já
    terminou com sucesso) — o trigger agendado (sábado/domingo 08:00 BRT) e o alarme SNS de
    falha continuam cobrindo o caso.

Notificação:
    Se nenhuma unidade falhou e trigger_agg=True, publica no tópico SNS de sucesso do
    backfill (SNS_TOPIC_ARN_BACKFILL_SUCCESS, opcional) — ver
    backfill_shared.notify_backfill_success. Suprimida junto com trigger_agg=False (chamado
    por backfill_historico.py), que notifica uma única vez ao final dos dois estágios.

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken
    do S3/Athena/Secrets Manager), o script sai com exit code 75
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
# Import fully-qualified (não "from src.utils import ...") de propósito: cada job Glue
# tem seu próprio pacote "src" (app/<modulo>/src/), e vários scripts/testes desse projeto
# já contam com o nome curto "src.utils" resolvendo para o módulo de SUA própria suite via
# manipulação de sys.path/sys.modules (ver test/conftest.py). Importar com o caminho
# completo evita colidir com esse mecanismo — não precisamos que "src.utils" (nome curto)
# resolva para nada aqui, só as três funções de app/glue_details/src/utils.py.
from app.glue_details.src.utils import (  # noqa: E402
    get_api_secret,
    run_details_and_watch_providers_for_year,
    trigger_glue_job,
)

import backfill_shared as shared

logger = shared.setup_logging()


def main(trigger_agg: bool = True) -> bool:
    region = shared.require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region

    table_group    = shared.require_env("TABLE_GROUP")
    s3_bucket_sot  = shared.require_env("S3_BUCKET_SOT")
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    db_movie       = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv          = shared.require_env("GLUE_DATABASE_TV")

    table_discover_movie        = shared.require_env("TABLE_DISCOVER_MOVIE")
    table_discover_tv           = shared.require_env("TABLE_DISCOVER_TV")
    table_details_movie         = shared.require_env("TABLE_DETAILS_MOVIE")
    table_details_tv            = shared.require_env("TABLE_DETAILS_TV")
    table_watch_providers_movie = shared.require_env("TABLE_WATCH_PROVIDERS_MOVIE")
    table_watch_providers_tv    = shared.require_env("TABLE_WATCH_PROVIDERS_TV")

    secret_arn  = shared.require_env("TMDB_SECRET_ARN")
    dq_job_name = shared.require_env("GLUE_DATA_QUALITY_JOB_NAME")

    start_year, end_year = shared.read_year_range()
    wait_seconds  = int(os.environ.get("WAIT_SECONDS", 15))
    force_refetch = os.environ.get("FORCE_REFETCH", "true").lower() == "true"
    translate_provider = shared.apply_translate_cost_guard(
        os.environ.get("TRANSLATE_PROVIDER", "google"), start_year, end_year,
    )

    s3_client = boto3.client("s3", region_name=region)

    years = list(range(start_year, end_year + 1))
    total_units = len(years) * 2
    logger.info(
        "Backfill de enriquecimento: %d anos (%d-%d) x 2 tipos = %d unidades | FORCE_REFETCH=%s",
        len(years), start_year, end_year, total_units, force_refetch,
    )

    # Busca a chave uma vez antes do loop — Secrets Manager tem custo por chamada.
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
        logger.info("[%d/%d] Enriquecendo | %s | year=%d", i, len(pendentes), media_type, year)

        table_discover        = table_discover_movie        if media_type == "movie" else table_discover_tv
        table_details         = table_details_movie         if media_type == "movie" else table_details_tv
        table_watch_providers = table_watch_providers_movie if media_type == "movie" else table_watch_providers_tv

        try:
            run_details_and_watch_providers_for_year(
                api_key=api_key,
                database=database,
                media_type=media_type,
                year=str(year),
                end_year=str(end_year),
                s3_bucket_sot=s3_bucket_sot,
                s3_bucket_temp=s3_bucket_temp,
                table_discover=table_discover,
                table_details=table_details,
                table_watch_providers=table_watch_providers,
                dq_job_name=dq_job_name,
                force_refetch=force_refetch,
                translate_provider=translate_provider,
                trigger_dq=False,
            )
        except ClientError as exc:
            if shared.is_expired_token_error(exc):
                logger.error(
                    "Credenciais AWS expiraram durante o enriquecimento de %s year=%d. O workflow "
                    "vai renovar a credencial e retomar do checkpoint automaticamente "
                    "(ver scripts/backfill_shared.py).",
                    media_type, year,
                )
                raise
            logger.error(
                "Falha ao enriquecer %s year=%d: %s. Continuando com o próximo...",
                media_type, year, exc,
            )
            failures.append((media_type, year, str(exc)))
        except Exception as exc:  # noqa: BLE001 — falha de uma unidade não deve abortar o backfill inteiro
            logger.error(
                "Falha ao enriquecer %s year=%d: %s. Continuando com o próximo...",
                media_type, year, exc,
            )
            failures.append((media_type, year, str(exc)))
        else:
            logger.info("Enriquecimento concluído com sucesso para %s year=%d.", media_type, year)
            completed.add(f"{media_type}:{year}")
            shared.save_checkpoint(s3_client, s3_bucket_temp, table_group, start_year, end_year, completed)

        if i < len(pendentes) and wait_seconds > 0:
            time.sleep(wait_seconds)

    logger.info("Backfill de enriquecimento concluído: %d unidades processadas.", len(pendentes))
    if failures:
        logger.error(
            "%d unidade(s) falharam e precisam ser re-executadas: %s",
            len(failures),
            ", ".join(f"{media_type}/{year} ({erro})" for media_type, year, erro in failures),
        )
    else:
        # Disparo único do Data Quality cobrindo todo o range processado, em vez de 2x por
        # unidade — mesmo padrão do modo "changes" de app/glue_details/main.py (YEAR aceita
        # lista de anos separada por vírgula).
        years_arg = ",".join(str(year) for year in years)
        logger.info(
            "Disparando Glue Data Quality uma única vez (YEAR=%s) para as 4 tabelas...", years_arg,
        )
        for table_name, database in (
            (table_details_movie, db_movie),
            (table_details_tv, db_tv),
            (table_watch_providers_movie, db_movie),
            (table_watch_providers_tv, db_tv),
        ):
            trigger_glue_job(dq_job_name, TABLE_NAME=table_name, DATABASE=database, YEAR=years_arg)
            time.sleep(5)
        if trigger_agg:
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
                table_group,
                f"Backfill de enriquecimento concluído sem pendências: {len(pendentes)} "
                f"unidade(s) processada(s) ({start_year}-{end_year}), Data Quality e Glue "
                f"AGG disparados.",
            )
        shared.clear_checkpoint(s3_client, s3_bucket_temp, table_group)

    return not failures


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
