"""
backfill_checkpoint.py — Checkpoint em S3 para retomada automática de backfills.

Usado pelos scripts que iteram por ano (backfill_historico.py,
backfill_enriquecimento.py, backfill_data_quality.py, backfill_traducao.py)
para persistir, a cada unidade de trabalho concluída (ex.: "movie:2020"),
o progresso em s3://{bucket}/_backfill_checkpoints/{table_group}.json.

Se o script for interrompido (ex.: ExpiredTokenException/ExpiredToken) e
reiniciado com o mesmo table_group e o mesmo range de anos, ele pula direto
para as unidades ainda não concluídas em vez de recomeçar do start_year.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger()


RETRYABLE_EXIT_CODE = 75

# ExpiredTokenException é o código retornado pelo STS (ex.: Lambda, Glue).
# ExpiredToken é o código equivalente retornado pelo S3 (ex.: ListObjectsV2
# via awswrangler, get_object/put_object/delete_object). Ambos indicam a
# mesma causa — credencial AWS expirada no meio de um backfill longo — e
# devem ser tratados como retomáveis.
_EXPIRED_TOKEN_CODES = frozenset({"ExpiredTokenException", "ExpiredToken"})


def _checkpoint_key(table_group: str) -> str:
    """Monta a chave S3 do checkpoint de um table_group."""
    return f"_backfill_checkpoints/{table_group}.json"


def is_expired_token_error(exc: ClientError) -> bool:
    """Indica se um `ClientError` representa uma credencial AWS expirada.

    Cobre tanto o código do STS (`ExpiredTokenException`, ex.: Lambda, Glue)
    quanto o do S3 (`ExpiredToken`, ex.: ListObjectsV2/get_object/put_object).

    Args:
        exc: exceção `ClientError` capturada em qualquer chamada AWS do backfill.

    Returns:
        `True` se o código do erro for um dos códigos de token expirado.
    """
    return exc.response.get("Error", {}).get("Code") in _EXPIRED_TOKEN_CODES


def expired_token_exit_code(exc: ClientError) -> int | None:
    """Traduz uma exceção de nível de processo para o exit code do script.

    Usado no bloco `if __name__ == "__main__":` de cada script de backfill:
    um erro de token expirado é retomável (o workflow renova a credencial
    e roda o script de novo, que retoma do checkpoint) — qualquer outro erro
    deve continuar propagando normalmente (exit code 1 com traceback).

    Args:
        exc: exceção `ClientError` capturada no nível mais externo do script.

    Returns:
        `RETRYABLE_EXIT_CODE` (75) se for um erro de token expirado, `None`
        caso contrário (o chamador deve relançar a exceção original).
    """
    if is_expired_token_error(exc):
        return RETRYABLE_EXIT_CODE
    return None


def log_expired_token(exc: ClientError, contexto: str) -> None:
    """Loga um erro claro se a credencial AWS expirou durante `contexto`."""
    if is_expired_token_error(exc):
        logger.error(
            "Credenciais AWS expiraram durante %s. O workflow vai renovar a credencial "
            "e retomar do checkpoint automaticamente (ver scripts/backfill_checkpoint.py).",
            contexto,
        )


def load_checkpoint(
    s3_client: Any, bucket: str, table_group: str, start_year: int, end_year: int,
) -> set[str]:
    """Lê o checkpoint salvo em S3 e retorna as unidades já concluídas.

    Args:
        s3_client: cliente boto3 do S3.
        bucket: bucket onde o checkpoint é armazenado.
        table_group: identifica o backfill (ex.: "detalhes_e_providers").
        start_year: ano inicial do run atual.
        end_year: ano final do run atual.

    Returns:
        Conjunto de unit_ids já concluídos. Vazio se não existir checkpoint ou
        se o range de anos salvo não bater com o run atual (nesse caso o
        checkpoint antigo é ignorado, não apagado).
    """
    key = _checkpoint_key(table_group)
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        codigo = exc.response.get("Error", {}).get("Code")
        if codigo in ("NoSuchKey", "404"):
            return set()
        log_expired_token(exc, f"leitura do checkpoint '{key}'")
        raise

    data = json.loads(response["Body"].read())
    if data.get("start_year") != start_year or data.get("end_year") != end_year:
        logger.warning(
            "Checkpoint '%s' tem range incompatível (start_year=%s, end_year=%s salvos "
            "vs. %s-%s do run atual). Ignorando e recomeçando do zero.",
            key, data.get("start_year"), data.get("end_year"), start_year, end_year,
        )
        return set()

    completed = set(data.get("completed", []))
    logger.info("Checkpoint '%s' encontrado: %d unidade(s) já concluída(s).", key, len(completed))
    return completed


def save_checkpoint(
    s3_client: Any, bucket: str, table_group: str, start_year: int, end_year: int, completed: set[str],
) -> None:
    """Sobrescreve o checkpoint em S3 com o conjunto atualizado de unidades concluídas."""
    key = _checkpoint_key(table_group)
    body = json.dumps({
        "start_year": start_year,
        "end_year": end_year,
        "completed": sorted(completed),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).encode()
    try:
        s3_client.put_object(Bucket=bucket, Key=key, Body=body)
    except ClientError as exc:
        log_expired_token(exc, f"escrita do checkpoint '{key}'")
        raise


def clear_checkpoint(s3_client: Any, bucket: str, table_group: str) -> None:
    """Remove o checkpoint em S3. Chamado quando o backfill termina sem falhas pendentes."""
    key = _checkpoint_key(table_group)
    try:
        s3_client.delete_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        log_expired_token(exc, f"remoção do checkpoint '{key}'")
        raise
    logger.info("Checkpoint '%s' removido — backfill concluído sem pendências.", key)
