"""
backfill_historico.py — Encadeia backfill_discover.py e backfill_enriquecimento.py.

Roda scripts/backfill_discover.py e, na sequência, scripts/backfill_enriquecimento.py, chamando o
main() de cada um diretamente no processo deste script (nunca via subprocess) — simula fora do
EventBridge o mesmo encadeamento que o pipeline automático faz via lambda_api -> glue_etl ->
glue_details para o modo discover, sem invocar Lambda nem acionar nenhum job Glue ETL/Details como
job (mesma filosofia dos dois scripts que encadeia).

Não reimplementa nenhuma lógica de coleta/transformação — a coleta TMDB, a transformação SOR->SOT
e o enriquecimento continuam existindo só dentro de backfill_discover.py/backfill_enriquecimento.py
(que por sua vez reaproveitam app/lambda_api/src/utils.py, app/glue_etl/src/utils.py e
app/glue_details/src/utils.py). Este script só orquestra a ordem e a retomada entre os dois.

Cada estágio mantém seu próprio checkpoint por ano/tipo (TABLE_GROUP="discover" e
TABLE_GROUP="detalhes_e_providers", os mesmos usados quando cada script roda sozinho) — chamar
backfill_historico.py não muda o comportamento de retomada de nenhum dos dois quando disparados
via backfill_discover.py/backfill_enriquecimento.py diretamente. Por cima disso, este script
mantém um checkpoint próprio (TABLE_GROUP="historico" interno, não configurável via env, com
unidades "discover"/"enriquecimento" em vez de tipo:ano) só para não redigitar um estágio que já
terminou 100% sem falhas (e por isso já limpou o próprio checkpoint) caso o estágio seguinte seja
interrompido por token expirado — sem esse marcador, retomar do zero reprocessaria o estágio
concluído inteiro (não incorreto, já que a escrita é idempotente, mas caro e lento à toa).

Se o estágio "discover" terminar com alguma unidade pendente (falha soft, não token expirado), o
backfill histórico é interrompido ali — "enriquecimento" não roda sobre um catálogo incompleto.
Rodar o workflow de novo com o mesmo range de anos retoma exatamente de onde parou, em ambos os
níveis de checkpoint.

Uso:
    python scripts/backfill_historico.py

Variáveis de ambiente: união das exigidas por backfill_discover.py e backfill_enriquecimento.py
(ver as docstrings dos dois), mais GLUE_DATABASE_MOVIE, GLUE_DATABASE_TV,
GLUE_DATA_QUALITY_JOB_NAME, S3_BUCKET_SPEC, S3_PREFIX_SPEC, DB_UNIFIED, TABLE_DISCOVER_UNIFIED e
ENVIRONMENT (usadas pelo disparo único ao Glue AGG, ver "Glue AGG" abaixo — as duas primeiras já
são lidas pelos dois estágios também, mas este script as lê de novo para o disparo próprio).
TABLE_GROUP não deve ser definida por quem chama este script: cada estágio define o próprio valor
("discover", depois "detalhes_e_providers") em os.environ antes de chamar o main() correspondente.

Data Quality:
    Não dispara Glue Data Quality diretamente — herda os disparos que backfill_discover.py (2
    tabelas: discover_movie, discover_tv) e backfill_enriquecimento.py (4 tabelas: details_movie,
    details_tv, watch_providers_movie, watch_providers_tv) já fazem sozinhos, cada um ao final do
    próprio estágio, só se esse estágio terminar sem falhas. Não existe um disparo único
    consolidando as 6 tabelas de uma vez.

Glue AGG:
    Diferente do Data Quality, o AGG É disparado uma única vez por este script, não herdado dos
    dois estágios: backfill_discover.main() e backfill_enriquecimento.main() são chamados com
    trigger_agg=False (suprimindo o disparo que cada um faria sozinho) e, se os dois estágios
    terminarem sem pendências, backfill_historico.py roda o Glue AGG ele mesmo, uma única vez,
    logo antes de limpar o checkpoint próprio — ver backfill_shared.trigger_agg_locally. Evita
    rodar a query de unificação (cara — CTAS sobre o catálogo inteiro) duas vezes seguidas por
    execução de "historico".

Notificação:
    Mesma lógica do AGG: notifica uma única vez, ao final, no tópico SNS de sucesso do backfill
    (SNS_TOPIC_ARN_BACKFILL_SUCCESS, opcional — ver backfill_shared.notify_backfill_success), e
    não nos dois estágios internos (chamados com trigger_agg=False, que também suprime a
    notificação de cada um) — evita 3 e-mails redundantes na mesma execução.

Retomada automática:
    Se a credencial AWS expirar (ExpiredTokenException do STS ou ExpiredToken do S3) durante
    qualquer um dos dois estágios, a exceção propaga naturalmente através deste script até
    backfill_shared.run_with_retry_exit, que traduz para o exit code 75
    (backfill_shared.RETRYABLE_EXIT_CODE) — mesmo contrato dos demais scripts de scripts/. O
    workflow renova a credencial e roda backfill_historico.py de novo: o checkpoint de estágio
    (s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/historico.json) pula estágios já concluídos
    sem falhas, e o checkpoint interno de cada estágio ainda em andamento pula as unidades
    (ano+tipo) já concluídas dentro dele.
"""

import os

import backfill_discover
import backfill_enriquecimento
import backfill_shared as shared
import boto3

logger = shared.setup_logging()

_TABLE_GROUP_HISTORICO = "historico"


def main() -> None:
    region = shared.require_env("AWS_REGION")
    os.environ["AWS_DEFAULT_REGION"] = region
    s3_bucket_temp = shared.require_env("S3_BUCKET_TEMP")
    db_movie    = shared.require_env("GLUE_DATABASE_MOVIE")
    db_tv       = shared.require_env("GLUE_DATABASE_TV")
    dq_job_name = shared.require_env("GLUE_DATA_QUALITY_JOB_NAME")
    start_year, end_year = shared.read_year_range()

    s3_client = boto3.client("s3", region_name=region)
    completed_stages = shared.load_checkpoint(
        s3_client, s3_bucket_temp, _TABLE_GROUP_HISTORICO, start_year, end_year,
    )

    if "discover" not in completed_stages:
        logger.info("=== Estágio 1/2 do backfill histórico: discover ===")
        os.environ["TABLE_GROUP"] = "discover"
        if not backfill_discover.main(trigger_agg=False):
            logger.error(
                "Estágio 'discover' terminou com unidades pendentes — backfill histórico "
                "interrompido antes de 'enriquecimento'. Rode de novo para retomar."
            )
            return
        completed_stages.add("discover")
        shared.save_checkpoint(
            s3_client, s3_bucket_temp, _TABLE_GROUP_HISTORICO, start_year, end_year, completed_stages,
        )
    else:
        logger.info("Estágio 'discover' já concluído no checkpoint — pulando para 'enriquecimento'.")

    if "enriquecimento" not in completed_stages:
        logger.info("=== Estágio 2/2 do backfill histórico: enriquecimento ===")
        os.environ["TABLE_GROUP"] = "detalhes_e_providers"
        if not backfill_enriquecimento.main(trigger_agg=False):
            logger.error("Estágio 'enriquecimento' terminou com unidades pendentes.")
            return
        completed_stages.add("enriquecimento")
        shared.save_checkpoint(
            s3_client, s3_bucket_temp, _TABLE_GROUP_HISTORICO, start_year, end_year, completed_stages,
        )
    else:
        logger.info("Estágio 'enriquecimento' já concluído no checkpoint.")

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
    shared.clear_checkpoint(s3_client, s3_bucket_temp, _TABLE_GROUP_HISTORICO)
    summary = "Backfill histórico concluído: discover + enriquecimento, sem pendências."
    logger.info(summary)
    shared.notify_backfill_success(_TABLE_GROUP_HISTORICO, summary)


if __name__ == "__main__":
    shared.run_with_retry_exit(main)
