"""
backfill_shared.py — Código comum aos scripts de backfill manual em scripts/.

Reúne o que hoje se repetia, byte-a-byte ou quase, em backfill_discover.py,
backfill_referencias.py, backfill_traducao.py, backfill_data_quality.py e
backfill_enriquecimento.py:

  - leitura de variável de ambiente obrigatória (`require_env`)
  - setup de logging (`setup_logging`)
  - leitura do range de anos do backfill (`read_year_range`)
  - wrapper de exit code 75 para retomada automática (`run_with_retry_exit`)
  - mensagem de log de progresso do checkpoint (`log_resume_progress`)
  - checkpoint em S3 para retomada automática de backfills (`load_checkpoint`,
    `save_checkpoint`, `clear_checkpoint` e helpers de token expirado)

Checkpoint em S3
----------------
Usado pelos scripts que iteram por ano (backfill_discover.py,
backfill_enriquecimento.py, backfill_data_quality.py, backfill_traducao.py)
para persistir, a cada unidade de trabalho concluída (ex.: "movie:2020"),
o progresso em s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{table_group}.json.

Se o script for interrompido (ex.: ExpiredTokenException/ExpiredToken) e
reiniciado com o mesmo table_group e o mesmo range de anos, ele pula direto
para as unidades ainda não concluídas em vez de recomeçar do start_year.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from botocore.exceptions import ClientError

_SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")


def _sao_paulo_converter(timestamp: float) -> time.struct_time:
    """Converte o timestamp do LogRecord para horário de São Paulo.

    Atribuído a `logging.Formatter.converter` (atributo de classe) logo abaixo
    — afeta `%(asctime)s` de todos os 7 scripts de backfill no processo
    inteiro, sem precisar duplicar configuração em cada `logging.basicConfig`.
    """
    return datetime.fromtimestamp(timestamp, tz=_SAO_PAULO_TZ).timetuple()


logging.Formatter.converter = staticmethod(_sao_paulo_converter)

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
logger = logging.getLogger()


RETRYABLE_EXIT_CODE = 75

# ExpiredTokenException é o código retornado pelo STS (ex.: Lambda, Glue).
# ExpiredToken é o código equivalente retornado pelo S3 (ex.: ListObjectsV2
# via awswrangler, get_object/put_object/delete_object). Ambos indicam a
# mesma causa — credencial AWS expirada no meio de um backfill longo — e
# devem ser tratados como retomáveis.
_EXPIRED_TOKEN_CODES = frozenset({"ExpiredTokenException", "ExpiredToken"})


def setup_logging() -> logging.Logger:
    """Retorna o logger configurado no nível de módulo (ver topo do arquivo)."""
    return logging.getLogger()


def require_env(name: str) -> str:
    """Lê variável de ambiente obrigatória ou levanta erro."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Variável de ambiente obrigatória não definida: {name}")
    return value


def apply_translate_cost_guard(translate_provider: str, start_year: int, end_year: int) -> str:
    """Rebaixa "aws" para "google" quando o intervalo pedido cobre mais de 1 ano.

    Proteção contra custo alto do AWS Translate (pago por caractere) para o caso de o
    operador escolher "aws" para testar um período curto e esquecer de voltar para
    "google" antes de disparar um backfill do catálogo histórico inteiro. AWS Translate
    continua disponível como fallback capado por caracteres via
    shared_utils.traducao.resolve_translate_fn, mesmo quando rebaixado aqui — só deixa
    de ser o serviço primário.

    Args:
        translate_provider: Valor pedido ("google" ou "aws").
        start_year:         Ano inicial do backfill.
        end_year:           Ano final do backfill.

    Returns:
        "google" se translate_provider="aws" e end_year > start_year; caso contrário,
        translate_provider sem alteração.
    """
    if translate_provider == "aws" and end_year > start_year:
        logger.warning(
            "TRANSLATE_PROVIDER='aws' pedido para %d-%d (mais de 1 ano) — rebaixando "
            "para 'google' automaticamente para evitar custo alto. AWS Translate "
            "continua disponível como fallback (capado) em resolve_translate_fn.",
            start_year, end_year,
        )
        return "google"
    return translate_provider


def read_year_range(
    start_env: str = "BACKFILL_START_YEAR",
    end_env: str = "BACKFILL_END_YEAR",
    start_default: int = 2000,
) -> tuple[int, int]:
    """Lê o range de anos do backfill a partir de variáveis de ambiente opcionais."""
    start_year = int(os.environ.get(start_env, start_default))
    end_year = int(os.environ.get(end_env, datetime.now().year))
    return start_year, end_year


def run_with_retry_exit(main_fn: Callable[[], object]) -> None:
    """Roda main_fn() e traduz token expirado no exit code 75 (retomável).

    Chamado explicitamente pelo bloco `if __name__ == "__main__":` de cada
    script que usa checkpoint. O workflow (.github/workflows/05_backfill.yml)
    reconhece o exit code 75, renova a credencial e roda o script de novo —
    como o progresso é lido do checkpoint em S3, as unidades já concluídas
    são puladas. `main_fn` pode retornar `None` (maioria dos scripts) ou
    `bool` (`backfill_discover.py`/`backfill_enriquecimento.py`, sinalizando
    se o backfill terminou sem falhas pendentes, consumido por
    `backfill_historico.py`) — o retorno é sempre ignorado aqui.
    """
    try:
        main_fn()
    except ClientError as exc:
        codigo = expired_token_exit_code(exc)
        if codigo is not None:
            sys.exit(codigo)
        raise


def log_resume_progress(log: logging.Logger, unidade_label: str, total: int, pendentes: int) -> None:
    """Loga quantas unidades de trabalho já foram concluídas, se houver progresso salvo.

    `unidade_label` é a frase já formatada que descreve as unidades concluídas
    (ex.: "invocações já concluídas", "runs já concluídos"), preservando a
    redação específica de cada script.
    """
    if pendentes < total:
        log.info(
            "%d de %d %s no checkpoint; retomando com %d pendente(s).",
            total - pendentes, total, unidade_label, pendentes,
        )


def _checkpoint_key(table_group: str) -> str:
    """Monta a chave S3 do checkpoint de um table_group."""
    return f"tmdb/backfill_checkpoints/{table_group}.json"


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
            "e retomar do checkpoint automaticamente (ver scripts/backfill_shared.py).",
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
