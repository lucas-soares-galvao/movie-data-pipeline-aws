"""
Lambda API — coleta dados da API TMDB e dispara o Glue ETL.
Fluxo: EventBridge → busca API key → coleta referências → coleta discover (por ano) → dispara Glue ETL.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from requests.exceptions import HTTPError
from shared_utils.api_client import get_api_secret
from shared_utils.triggers import trigger_glue_job
from src.utils import (
    collect_changes_data,
    collect_configuration_data,
    collect_discover_data,
    collect_genre_data,
    collect_now_playing_data,
    collect_watch_providers_ref,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Variáveis de ambiente injetadas pelo Terraform (lambda_api.tf, bloco environment da aws_lambda_function).
TMDB_SECRET_ARN = os.environ["TMDB_SECRET_ARN"]
GLUE_ETL_JOB_NAME = os.environ["GLUE_ETL_JOB_NAME"]
GLUE_DETAILS_JOB_NAME = os.environ["GLUE_DETAILS_JOB_NAME"]
GLUE_AGG_JOB_NAME = os.environ["GLUE_AGG_JOB_NAME"]
S3_BUCKET_SOR = os.environ["S3_BUCKET_SOR"]
S3_BUCKET_TEMP = os.environ["S3_BUCKET_TEMP"]


def _wait_for_reference_jobs(job_name: str, run_ids: list[str], poll_interval: int = 15) -> None:
    """Aguarda cada run_id de `job_name` atingir um estado terminal.

    `trigger_glue_job` é fire-and-forget (ver shared_utils.triggers) — sem isso, o Glue AGG
    disparado logo em seguida (modo skip_weekly, ver lambda_handler) poderia começar a ler as
    tabelas de referência no Athena antes do Glue ETL terminar de escrevê-las, unindo dados
    desatualizados. Não aborta em caso de falha: loga e segue, para não perder a atualização
    das tabelas que tiveram sucesso.
    """
    glue_client = boto3.client("glue")
    for run_id in run_ids:
        while True:
            state = glue_client.get_job_run(JobName=job_name, RunId=run_id)["JobRun"]["JobRunState"]
            if state in ("SUCCEEDED", "FAILED", "STOPPED", "ERROR", "TIMEOUT"):
                if state != "SUCCEEDED":
                    logger.error(
                        f"Job '{job_name}' (run_id={run_id}) terminou em '{state}' — Glue AGG "
                        "será acionado mesmo assim, com essa tabela de referência desatualizada."
                    )
                break
            time.sleep(poll_interval)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Coleta dados do TMDB e dispara o Glue ETL. Payload definido em eventbridge_lambda_api.tf."""
    s3_client = boto3.client("s3")

    content_type = event["type"]

    # Modo changes (Changes API do TMDB) — refresca títulos já existentes no catálogo,
    # de qualquer ano, que mudaram numa janela de data recente. Estruturalmente diferente
    # dos demais modos: não usa /discover, não escreve no SOR nem passa pelo Glue ETL —
    # produz uma lista de IDs e aciona o Glue Details diretamente. Por isso sai cedo, antes
    # da resolução de tabelas de referência (o payload desse modo não as inclui).
    if event.get("only_changes_tables", False):
        logger.info("Buscando chave de API do TMDB no Secrets Manager...")
        api_key = get_api_secret(TMDB_SECRET_ARN, "tmdb_api_key")
        s3_key = collect_changes_data(api_key, s3_client, S3_BUCKET_TEMP, content_type)
        trigger_glue_job(
            GLUE_DETAILS_JOB_NAME,
            MEDIA_TYPE=content_type,
            DATABASE=event["database"],
            CHANGES_S3_PATH=f"s3://{S3_BUCKET_TEMP}/{s3_key}",
            TRANSLATE_PROVIDER=event.get("translate_provider", "google"),
        )
        logger.info(f"Coleta de changes de '{content_type}' finalizada com sucesso!")
        return {
            "statusCode": 200,
            "body": f"Changes de '{content_type}' processados com sucesso.",
        }

    # Modo rotation refresh — percorre o catálogo antigo (2000 até current_year - 3)
    # um ano por execução, via um ponteiro simples em SSM Parameter Store (não é
    # checkpoint de loop — cada invocação é independente e stateless, só lê/escreve
    # "qual foi o último ano"). O ponteiro avança 1 e reinicia em 2000 ao ultrapassar
    # o limite; o limite é recalculado a cada execução a partir da data corrente
    # (nunca hardcoded), então o range acompanha sozinho o catálogo envelhecendo, sem
    # exigir ajuste manual de ano em ano. Um parâmetro por content_type evita corrida
    # entre as execuções de movie e tv (schedules independentes no EventBridge).
    if event.get("only_rotation_refresh", False):
        ssm = boto3.client("ssm")
        param_name = f"/tmdb-pipeline/rotation-year-pointer-{content_type}"
        last_year = int(ssm.get_parameter(Name=param_name)["Parameter"]["Value"])

        current_year = datetime.now(tz=timezone.utc).year
        oldest_active_year = current_year - 3
        next_year = last_year + 1
        if next_year > oldest_active_year:
            next_year = 2000

        trigger_glue_job(
            GLUE_DETAILS_JOB_NAME,
            MEDIA_TYPE=content_type,
            DATABASE=event["database"],
            YEAR=next_year,
            END_YEAR=next_year,
            FORCE_REFETCH=True,
            TRANSLATE_PROVIDER=event.get("translate_provider", "google"),
        )
        ssm.put_parameter(Name=param_name, Value=str(next_year), Overwrite=True)
        logger.info(f"Rotation refresh de '{content_type}' finalizado com sucesso! Ano processado: {next_year}")
        return {
            "statusCode": 200,
            "body": f"Rotation refresh de '{content_type}' (ano {next_year}) processado com sucesso.",
        }

    # "google" é o default do caminho automático via EventBridge: o payload configurado em
    # eventbridge.tf nunca define translate_provider, então cai aqui — é grátis, e o AWS
    # Translate continua disponível como fallback automático (capado por caracteres) via
    # shared_utils.traducao.resolve_translate_fn. Backfills manuais podem sobrescrever
    # para "aws" para testar tradução real da AWS num período curto.
    translate_provider = event.get("translate_provider", "google")

    glue_base_args = {
        "MEDIA_TYPE": content_type,
        "DATABASE": event["database"],
        "DATABASE_UNIFIED": event["database_unified"],
        "TRANSLATE_PROVIDER": translate_provider,
    }

    if content_type == "movie":
        table_genre = event["table_genre_movie"]
        table_configuration = event["table_configuration_languages"]
        table_discover = event["table_discover_movie"]
        table_watch_providers_ref = event["table_watch_providers_ref_movie"]
        table_now_playing = event.get("table_now_playing_movie")
    else:
        table_genre = event["table_genre_tv"]
        table_configuration = event["table_configuration_countries"]
        table_discover = event["table_discover_tv"]
        table_watch_providers_ref = event["table_watch_providers_ref_tv"]
        table_now_playing = None  # TV não tem now_playing

    # Flags de controle definidas no payload do EventBridge (ver eventbridge.tf).
    # Cada flag ativa um "modo" de execução diferente:
    #
    # Modo           | only_weekly | only_annual | only_monthly | skip_weekly | O que roda
    # ---------------|-------------|-------------|--------------|-------------|-----------------------------
    # Semanal        |    True     |    False    |    False     |    False    | discover + now_playing (sem referências)
    # Mensal         |    False    |    False    |    True      |    False    | referências + discover do ano anterior
    # Anual backfill |    False    |    True     |    False     |    False    | discover histórico (sem referências)
    # Só referências |    False    |    False    |    False     |    True     | genre + config + watch_providers_ref
    #
    # Modo "Só referências": não passa pelo discover/Glue Details, então o Glue AGG não seria
    # acionado pelo cascade normal (Glue Details "tv + end_year" — ver app/glue_details/main.py).
    # Para que a atualização de referências chegue à camada SPEC sem esperar o próximo ciclo
    # semanal/mensal, este modo aciona o Glue AGG diretamente ao final — só no run de "tv" (mesma
    # convenção do resto do pipeline: tv é a perna que fecha o ciclo, tanto no EventBridge — roda
    # 5 min depois de movie — quanto em scripts/backfill_referencias.py, que invoca movie e
    # depois tv de forma síncrona). Antes de acionar o AGG, aguarda (_wait_for_reference_jobs) os
    # 3 Glue ETL de referência que esta mesma invocação (tv) acabou de disparar — trigger_glue_job
    # é fire-and-forget, então sem essa espera o AGG poderia ler as tabelas de tv ainda com o dado
    # antigo. Não espera pelos jobs de "movie" (invocação anterior, separada) — como no resto do
    # pipeline, isso depende do intervalo entre as duas invocações (5 min no EventBridge, 300s em
    # backfill_referencias.py) já ser suficiente para o Glue ETL de referência de movie terminar.
    #
    # only_changes_tables e only_rotation_refresh (tratados acima, antes desta tabela)
    # não combinam com as flags abaixo — saem cedo, direto para o Glue Details, sem
    # passar por /discover nem Glue ETL:
    #   only_changes_tables   — refresh dos ids que a TMDB reportou mudados (Changes API)
    #   only_rotation_refresh — refresh forçado de 1 ano do catálogo antigo por vez (FORCE_REFETCH)
    #
    # O ano corrente e o anterior não têm um modo forçado equivalente: já são
    # refeitos naturalmente pelo cascade do discover semanal/mensal -> Glue ETL ->
    # Glue Details (sem FORCE_REFETCH, mas a lógica de delta do Glue Details já
    # refaz qualquer id não tocado no mês calendário corrente) — ver
    # app/glue_etl/main.py (table_type == "discover").
    only_weekly_tables = event.get("only_weekly_tables", False)
    only_annual_tables = event.get("only_annual_tables", False)
    skip_weekly = event.get("skip_weekly", False)
    only_monthly_tables = event.get("only_monthly_tables", False)
    # Modos semanal e anual pulam referências porque elas mudam raramente (gêneros, idiomas, países)
    # e não precisam ser atualizadas a cada coleta de discover.
    skip_reference = only_weekly_tables or only_annual_tables

    # Busca a API key uma vez antes do loop — Secrets Manager tem custo por chamada.
    logger.info("Buscando chave de API do TMDB no Secrets Manager...")
    api_key = get_api_secret(TMDB_SECRET_ARN, "tmdb_api_key")

    current_year   = datetime.now(tz=timezone.utc).year
    start_year     = int(event.get("start_year", current_year))
    end_year       = int(event.get("end_year",   current_year))
    loop_end_year  = int(event.get("loop_end_year", end_year))

    # Modo mensal: ignora os anos do payload e força o ano anterior.
    # O EventBridge envia um payload padrão com os anos do ciclo corrente, mas o modo mensal
    # sempre quer re-coletar o ano anterior (ex: em 2025, recoleta o discover de 2024).
    # Sobrescrever aqui evita criar um payload separado para o trigger mensal.
    if only_monthly_tables:
        start_year = current_year - 1
        end_year = current_year - 1
        loop_end_year = current_year - 1

    # Run IDs dos 3 Glue ETL de referência acionados abaixo — usados só pelo modo skip_weekly
    # (ver bloco "if skip_weekly" logo adiante) para aguardar essas escritas antes do Glue AGG.
    reference_run_ids: list[str] = []

    if not skip_reference:
        logger.info(f"Coletando gêneros do TMDB para '{content_type}'...")
        collect_genre_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de gêneros...")
        reference_run_ids.append(trigger_glue_job(
            GLUE_ETL_JOB_NAME,
            TABLE_TYPE="genre",
            TABLE_NAME=table_genre,
            **glue_base_args,
        ))

        logger.info(f"Coletando configurações do TMDB para '{content_type}'...")
        collect_configuration_data(api_key, s3_client, S3_BUCKET_SOR, content_type)
        logger.info("Acionando Glue ETL para tabela de configuração...")
        reference_run_ids.append(trigger_glue_job(
            GLUE_ETL_JOB_NAME,
            TABLE_TYPE="configuration",
            TABLE_NAME=table_configuration,
            **glue_base_args,
        ))

        logger.info(f"Coletando referência de watch providers do TMDB para '{content_type}'...")
        try:
            collect_watch_providers_ref(api_key, s3_client, S3_BUCKET_SOR, content_type)
            logger.info("Acionando Glue ETL para tabela de watch providers de referência...")
            reference_run_ids.append(trigger_glue_job(
                GLUE_ETL_JOB_NAME,
                TABLE_TYPE="watch_providers_ref",
                TABLE_NAME=table_watch_providers_ref,
                **glue_base_args,
            ))
        except HTTPError:
            logger.error(
                f"Falha ao coletar watch_providers_ref para '{content_type}'. "
                "Pulando — dados anteriores no S3 permanecem válidos."
            )
    else:
        logger.info("skip_reference=True: pulando coleta de genre, configuration e watch_providers_ref.")

    if skip_weekly:
        logger.info("skip_weekly=True: pulando coleta de discover.")
        if content_type == "tv":
            logger.info(
                "skip_weekly=True (tv): aguardando os %d Glue ETL de referência desta invocação "
                "terminarem antes de acionar o Glue AGG...", len(reference_run_ids),
            )
            _wait_for_reference_jobs(GLUE_ETL_JOB_NAME, reference_run_ids)
            logger.info("Referências de tv atualizadas — acionando Glue AGG.")
            trigger_glue_job(GLUE_AGG_JOB_NAME)
        return {
            "statusCode": 200,
            "body": f"Coleta de referência de '{content_type}' finalizada com sucesso.",
        }

    logger.info(
        f"Iniciando coleta do TMDB ({content_type}) de {start_year} até {loop_end_year}..."
    )

    # loop_end_year pode ser menor que end_year em backfills particionados por ano
    for year in range(start_year, loop_end_year + 1):
        logger.info(f"=== Ano: {year} | Tipo: {content_type} ===")

        collect_discover_data(
            api_key=api_key,
            s3_client=s3_client,
            bucket=S3_BUCKET_SOR,
            content_type=content_type,
            folder=f"tmdb/discover/{content_type}",
            year=year,
        )

        # end_year é repassado para o Glue Details saber quando é o último run do ciclo
        # (tv + end_year → dispara o Glue AGG).
        trigger_glue_job(
            GLUE_ETL_JOB_NAME,
            TABLE_TYPE="discover",
            TABLE_NAME=table_discover,
            YEAR=year,
            END_YEAR=end_year,
            **glue_base_args,
        )

    if content_type == "movie" and table_now_playing and not only_monthly_tables:
        logger.info("Coletando filmes em cartaz nos cinemas...")
        collect_now_playing_data(api_key, s3_client, S3_BUCKET_SOR)
        logger.info("Acionando Glue ETL para tabela de now_playing...")
        trigger_glue_job(
            GLUE_ETL_JOB_NAME,
            TABLE_TYPE="now_playing",
            TABLE_NAME=table_now_playing,
            **glue_base_args,
        )

    logger.info(f"Coleta de '{content_type}' finalizada com sucesso!")
    return {
        "statusCode": 200,
        "body": f"Dados de '{content_type}' coletados de {start_year} a {loop_end_year} com sucesso.",
    }
