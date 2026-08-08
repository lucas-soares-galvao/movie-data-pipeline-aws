"""
backfill_shared.py — Código comum aos scripts de backfill manual em scripts/.

Reúne o que hoje se repetia, byte-a-byte ou quase, em backfill_historico.py,
backfill_referencias.py, backfill_traducao.py, backfill_data_quality.py e
backfill_enriquecimento.py:

  - leitura de variável de ambiente obrigatória (`require_env`)
  - setup de logging (`setup_logging`)
  - invocação síncrona da Lambda API (`invoke_lambda_sync`)
  - payloads base de movie/tv para a Lambda API (`build_base_payloads`)
  - leitura do range de anos do backfill (`read_year_range`)
  - wrapper de exit code 75 para retomada automática (`run_with_retry_exit`)
  - mensagem de log de progresso do checkpoint (`log_resume_progress`)
  - checkpoint em S3 para retomada automática de backfills (`load_checkpoint`,
    `save_checkpoint`, `clear_checkpoint` e helpers de token expirado)

Checkpoint em S3
----------------
Usado pelos scripts que iteram por ano (backfill_historico.py,
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
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import boto3
from botocore.config import Config
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

# > timeout do Lambda (900s, ver infra/lambda_api.tf). O default do boto3 (read_timeout=60s) já
# não bastava mesmo antes: a extinta flag skip_weekly (removida de app/lambda_api/main.py —
# a coleta de referências que ela cobria roda hoje diretamente no processo do backfill, ver
# scripts/backfill_referencias.py) chegou a esperar (get_job_run) os Glue ETL de referência
# terminarem antes de acionar o Glue AGG, o que podia passar de 60s. Sem esse ajuste, o boto3
# desiste (ReadTimeoutError) achando que a invocação falhou, mas a Lambda continua rodando
# "órfã" em background na AWS.
#
# Pior: por padrão o botocore RETENTA automaticamente uma requisição que sofreu
# ReadTimeoutError (visível na stack trace passando por retryhandler.py antes de propagar).
# `lambda:Invoke` não é idempotente — não existe token de idempotência para essa API — então
# cada retry automático do botocore dispara uma execução da Lambda inteiramente nova e
# concorrente com a anterior (ainda rodando em background), não uma "nova tentativa" no sentido
# usual. Incidente real (histórico, sob a extinta skip_weekly): uma única chamada
# client.invoke() gerou 5 execuções órfãs da Lambda (perna tv), cada uma dessas triggando seu
# próprio Glue AGG e reacionando os 3 Glue ETL de referência em paralelo — causa de uma corrida
# de escrita/leitura no S3 (Glue Data Quality lendo um parquet que uma execução concorrente
# acabou de sobrescrever). Por isso, além do read_timeout alto, max_attempts=1 desliga esse
# retry automático — uma falha aqui deve terminar o script (o workflow trata isso normalmente,
# sem retry automático para backfill_historico.py, hoje o único chamador de
# invoke_lambda_sync — ver .github/workflows/05_backfill.yml) em vez de silenciosamente
# multiplicar execuções de uma operação não-idempotente.
LAMBDA_READ_TIMEOUT_SECONDS = 910

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


def build_lambda_client(region: str) -> Any:
    """Cliente boto3 da Lambda com read_timeout alto e retry automático desligado.

    Usar sempre no lugar de `boto3.client("lambda", region_name=region)` direto — ver
    LAMBDA_READ_TIMEOUT_SECONDS para o racional. `max_attempts=1` desliga o retry automático do
    botocore: como `lambda:Invoke` não é idempotente, um retry silencioso após timeout dispara
    uma execução nova e concorrente da Lambda em vez de reenviar a mesma chamada com segurança.
    """
    return boto3.client(
        "lambda",
        region_name=region,
        config=Config(
            read_timeout=LAMBDA_READ_TIMEOUT_SECONDS,
            connect_timeout=10,
            retries={"max_attempts": 1},
        ),
    )


def invoke_lambda_sync(client: Any, function_name: str, payload: dict[str, Any]) -> None:
    """Invoca a Lambda de forma síncrona e lança exceção se falhar."""
    try:
        response = client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
    except ClientError as exc:
        log_expired_token(exc, f"invocação da Lambda '{function_name}'")
        raise
    status = response["StatusCode"]
    body = json.loads(response["Payload"].read())

    if status != 200 or "FunctionError" in response:
        raise RuntimeError(f"Lambda retornou erro: {body}")

    logger.info("Lambda OK: %s", body.get("body", body))


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


def build_base_payloads(
    start_year: Optional[int] = None, end_year: Optional[int] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Monta os payloads base de movie/tv enviados à Lambda API.

    Espelha exatamente o que o EventBridge envia (eventbridge_lambda_api.tf), com um
    campo a mais: "translate_provider" (opcional via env TRANSLATE_PROVIDER, default
    "google" — mesmo default do caminho automático via EventBridge desde que o Glue
    ETL/Details passou a usar Google como primário e AWS Translate como fallback
    automático). Ver shared_utils.traducao.resolve_translate_fn.

    Se start_year/end_year forem informados, aplica apply_translate_cost_guard antes
    de montar os payloads — usado por backfill_historico.py, que itera por ano.
    backfill_referencias.py não informa esses parâmetros (não depende de ano, então o
    guard não se aplica).

    Args:
        start_year: Ano inicial do backfill, ou None se não depender de ano.
        end_year:   Ano final do backfill, ou None se não depender de ano.
    """
    translate_provider = os.environ.get("TRANSLATE_PROVIDER", "google")
    if start_year is not None and end_year is not None:
        translate_provider = apply_translate_cost_guard(translate_provider, start_year, end_year)

    base_movie = {
        "type":                            "movie",
        "database":                        require_env("GLUE_DATABASE_MOVIE"),
        "database_unified":                require_env("GLUE_DATABASE_UNIFIED"),
        "table_discover_movie":            require_env("TABLE_DISCOVER_MOVIE"),
        "table_genre_movie":               require_env("TABLE_GENRE_MOVIE"),
        "table_configuration_languages":   require_env("TABLE_CONFIGURATION_LANGUAGES"),
        "table_watch_providers_ref_movie": require_env("TABLE_WATCH_PROVIDERS_REF_MOVIE"),
        "translate_provider":              translate_provider,
    }

    base_tv = {
        "type":                          "tv",
        "database":                      require_env("GLUE_DATABASE_TV"),
        "database_unified":              require_env("GLUE_DATABASE_UNIFIED"),
        "table_discover_tv":             require_env("TABLE_DISCOVER_TV"),
        "table_genre_tv":                require_env("TABLE_GENRE_TV"),
        "table_configuration_countries": require_env("TABLE_CONFIGURATION_COUNTRIES"),
        "table_watch_providers_ref_tv":  require_env("TABLE_WATCH_PROVIDERS_REF_TV"),
        "translate_provider":            translate_provider,
    }

    return base_movie, base_tv


def read_year_range(
    start_env: str = "BACKFILL_START_YEAR",
    end_env: str = "BACKFILL_END_YEAR",
    start_default: int = 2000,
) -> tuple[int, int]:
    """Lê o range de anos do backfill a partir de variáveis de ambiente opcionais."""
    start_year = int(os.environ.get(start_env, start_default))
    end_year = int(os.environ.get(end_env, datetime.now().year))
    return start_year, end_year


def run_with_retry_exit(main_fn: Callable[[], None]) -> None:
    """Roda main_fn() e traduz token expirado no exit code 75 (retomável).

    Chamado explicitamente pelo bloco `if __name__ == "__main__":` de cada
    script que usa checkpoint. O workflow (.github/workflows/05_backfill.yml)
    reconhece o exit code 75, renova a credencial e roda o script de novo —
    como o progresso é lido do checkpoint em S3, as unidades já concluídas
    são puladas.
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
