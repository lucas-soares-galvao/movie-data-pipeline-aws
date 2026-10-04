"""secret_redaction.py — Mascaramento de segredos em logs e exceções.

A API v3 do TMDB recebe a chave como parâmetro de query, e as exceções do `requests` embutem a URL
completa na mensagem ("404 Client Error: Not Found for url: ...?api_key=..."): qualquer
`logger.warning(f"...: {exc}")`, `logger.exception(...)` ou traceback não tratado imprime a chave.
Num repositório público isso vaza no log do GitHub Actions (aconteceu num run de backfill de dev).

Defesa em camadas: scrub_exception limpa a exceção na origem (também cobre tracebacks que o
`logging` não vê, como os do Lambda/Glue/Actions), RedactingFormatter limpa tudo o que passa pelos
handlers, e register_secret faz o mascaramento por valor para segredos que não casam nenhum padrão.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, TypeVar
from urllib.parse import quote

__all__ = [
    "MASK",
    "RedactingFormatter",
    "install_log_redaction",
    "redact",
    "register_secret",
    "scrub_exception",
]

MASK = "***"

# Valores menores que isso não são mascarados por valor: um "segredo" curto (ou vazio) casaria
# trechos comuns de qualquer log e o deixaria ilegível.
_MIN_SECRET_LENGTH = 8

_E = TypeVar("_E", bound=BaseException)

_lock = threading.Lock()
_secrets: set[str] = set()

# Padrões genéricos, que funcionam mesmo antes de qualquer segredo ser registrado.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Parâmetro de query com a chave (TMDB e afins): para no próximo separador de URL/texto.
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token)=([^&\s'\"<>)]+)"), rf"\1={MASK}"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), f"Bearer {MASK}"),
    # Chaves do OpenRouter (llm_api_key).
    (re.compile(r"\bsk-or-[A-Za-z0-9_-]{8,}"), f"sk-or-{MASK}"),
    # Access Key IDs da AWS (permanentes AKIA, temporárias ASIA).
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), rf"\1{MASK}"),
)


def register_secret(value: Any) -> None:
    """Registra um segredo para ser mascarado por valor, onde quer que apareça em logs/exceções.

    Guarda também a versão URL-encoded, que é a que aparece dentro de uma URL. Ignora o que não é
    string e valores com menos de _MIN_SECRET_LENGTH caracteres.

    Args:
        value: Valor do segredo (ex.: a chave do TMDB lida do Secrets Manager).
    """
    if not isinstance(value, str) or len(value) < _MIN_SECRET_LENGTH:
        return
    with _lock:
        _secrets.add(value)
        _secrets.add(quote(value, safe=""))


def redact(text: str) -> str:
    """Devolve text com os segredos registrados e os padrões conhecidos trocados por "***".

    Args:
        text: Texto a limpar (mensagem de log, mensagem de exceção, traceback).

    Returns:
        O mesmo texto, sem os segredos.
    """
    with _lock:
        known = sorted(_secrets, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, MASK)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def scrub_exception(exc: _E) -> _E:
    """Limpa a mensagem da exceção e corta a cadeia de causas, devolvendo a mesma exceção.

    A cadeia (`__cause__`/`__context__`) é cortada porque o traceback encadeado imprimiria a
    exceção original, com a mensagem — e a chave — que acabamos de limpar. Pensada para ser usada
    com `raise scrub_exception(exc)` dentro do próprio `except` (a mesma exceção, então o Python
    não a religa como contexto).

    Args:
        exc: Exceção capturada (ex.: HTTPError/ConnectionError do requests).

    Returns:
        A própria exc, com args limpos e sem cadeia.
    """
    exc.args = tuple(redact(str(arg)) if isinstance(arg, (str, BaseException)) else arg for arg in exc.args)
    exc.__cause__ = None
    exc.__context__ = None
    exc.__suppress_context__ = True
    return exc


class RedactingFormatter(logging.Formatter):
    """Envolve um formatter existente e aplica redact() ao texto final (mensagem + traceback)."""

    def __init__(self, inner: logging.Formatter | None = None) -> None:
        super().__init__()
        self._inner = inner or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return redact(self._inner.format(record))


def install_log_redaction(logger: logging.Logger | None = None) -> None:
    """Passa o formatter de cada handler do logger (raiz por padrão) por RedactingFormatter.

    Preserva o formato de cada handler (envolve o formatter atual em vez de substituí-lo),
    inclusive o do runtime do Lambda, que já instala o próprio handler antes do código rodar.
    Idempotente: chamar de novo não envolve duas vezes.

    Args:
        logger: Logger cujos handlers serão protegidos; o logger raiz se omitido.
    """
    for handler in (logger or logging.getLogger()).handlers:
        if not isinstance(handler.formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(handler.formatter))
