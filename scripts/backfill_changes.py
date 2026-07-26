"""
backfill_changes.py — Dispara manualmente o modo changes da Lambda API (TMDB Changes API).

Invoca a Lambda uma vez para movie e uma vez para tv com only_changes_tables=True —
o mesmo modo que o EventBridge já aciona automaticamente todo domingo (ver
infra/eventbridge.tf). A janela de busca é sempre [hoje - 8 dias, hoje], calculada
internamente por collect_changes_data (app/lambda_api/src/utils.py) — este script não
aceita nem precisa de datas. Útil para rodar sob demanda quando o cron semanal falhou
ou foi pulado, sem esperar até o próximo domingo.

Cada invocação aciona o Glue Details diretamente (sem passar por /discover nem Glue
ETL) — ver app/lambda_api/main.py e app/glue_details/src/utils.py.

Uso:
    python scripts/backfill_changes.py

Variáveis de ambiente obrigatórias (copie de infra/terraform.tfvars ou outputs):
    AWS_REGION
    LAMBDA_FUNCTION_NAME
    GLUE_DATABASE_MOVIE
    GLUE_DATABASE_TV

Variáveis opcionais:
    TRANSLATE_PROVIDER (padrão: "google")
"""

import os
import time

import boto3

import backfill_shared as shared

logger = shared.setup_logging()


def main() -> None:
    region         = shared.require_env("AWS_REGION")
    function_name  = shared.require_env("LAMBDA_FUNCTION_NAME")
    database_movie = shared.require_env("GLUE_DATABASE_MOVIE")
    database_tv    = shared.require_env("GLUE_DATABASE_TV")
    translate_provider = os.environ.get("TRANSLATE_PROVIDER", "google")

    client       = boto3.client("lambda", region_name=region)
    wait_seconds = 300

    payload_movie = {"type": "movie", "database": database_movie, "only_changes_tables": True, "translate_provider": translate_provider}
    payload_tv    = {"type": "tv",    "database": database_tv,    "only_changes_tables": True, "translate_provider": translate_provider}

    logger.info("Disparando changes (janela padrão de 8 dias) — 2 invocações")

    logger.info("[1/2] movie | changes")
    shared.invoke_lambda_sync(client, function_name, payload_movie)
    logger.info("Aguardando %d segundos antes da próxima invocação...", wait_seconds)
    time.sleep(wait_seconds)

    logger.info("[2/2] tv    | changes")
    shared.invoke_lambda_sync(client, function_name, payload_tv)

    logger.info("Changes disparado com sucesso.")


if __name__ == "__main__":
    main()
