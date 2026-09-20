"""traducao_google.py — Tradução para português via Google Translate (deep_translator)."""

from __future__ import annotations

import logging
import re
import time

from deep_translator import GoogleTranslator

logger = logging.getLogger()

_MAX_ATTEMPTS = 5
_MAX_ATTEMPTS_NO_ERROR = 2

# Página de erro do Google devolvida no lugar da tradução (observado: "Error 500 (Server
# Error)!!1500.That’s an error. There was an error. Please try again later...").
# Ancorada no início e no formato "Error <status> (<motivo>)!!<n>" para não casar com uma
# tradução legítima que apenas mencione "Error" — o padrão vale para qualquer status HTTP.
_GOOGLE_ERROR_PAGE_PATTERN = re.compile(r"^Error \d{3} \([^)]*\)!!\d")


def is_google_error_page(text: object) -> bool:
    """True se `text` é a página de erro do Google Translate, e não uma tradução.

    Aceita qualquer tipo (o valor vem de colunas de DataFrame, onde pode ser None/NaN);
    só uma string que começa com o padrão de erro conta.
    """
    return isinstance(text, str) and _GOOGLE_ERROR_PAGE_PATTERN.match(text) is not None


class _GoogleErrorPageError(Exception):
    """O Google respondeu com a página de erro em vez de uma tradução."""


def translate_text(text: str, context: str = "") -> str:
    """
    Traduz texto para português via Google Translate, detectando automaticamente
    o idioma de origem (source="auto").

    Faz até _MAX_ATTEMPTS tentativas com backoff entre elas, já que o
    endpoint não-oficial do Google Translate falha esporadicamente sob alto
    volume de chamadas paralelas. Duas formas de falha contam como tentativa
    malsucedida:
      - a chamada lançar exceção — tende a ser transitório (rede, rate limit),
        por isso usa o orçamento completo de _MAX_ATTEMPTS;
      - retornar normalmente um texto idêntico ao original — na maioria das
        vezes indica que não há o que traduzir (nome próprio, termo
        emprestado como "anime"/"hotel"), não bloqueio transitório, por isso
        desiste mais cedo (_MAX_ATTEMPTS_NO_ERROR).
    Uma terceira forma de falha é o Google devolver a página de erro dele (ver
    is_google_error_page) como se fosse a tradução: sem essa checagem o texto de erro
    seria gravado como tradução (já aconteceu, em name_pt/overview_pt). Conta como
    tentativa com erro (backoff completo, como uma exceção) e, ao esgotar, loga um
    WARNING — diferente dos demais desfechos (DEBUG), porque indica bloqueio real do
    Google e não é visível de outra forma.
    Retorna o texto original se todas as tentativas aplicáveis se esgotarem,
    para não interromper o job.

    Args:
        text:    Texto a ser traduzido (idioma de origem detectado automaticamente).
        context: Descrição opcional do item traduzido (usada no log).

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar.
    """
    if not text:
        return ""
    prefix = f"{context} " if context else ""
    attempts_no_error = 0
    error_page: str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            result = GoogleTranslator(source="auto", target="pt").translate(text)
            # Só é falha se o próprio texto de entrada não for uma página de erro (senão
            # nunca haveria como "traduzir" e cada tentativa seria descartada em vão).
            if is_google_error_page(result) and not is_google_error_page(text):
                raise _GoogleErrorPageError(result)
        except _GoogleErrorPageError as exc:
            error_page = str(exc)
            logger.debug(f"Tentativa {attempt} de traduzir {prefix}'{text:.80}' devolveu a página de erro do Google.")
        # Chamada de API externa, tenta de novo no próximo loop.
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Tentativa {attempt} de traduzir {prefix}'{text}' falhou: {exc}")
        else:
            if result and result != text:
                return result
            attempts_no_error += 1
            logger.debug(
                f"Tentativa {attempt} de traduzir {prefix}'{text:.80}' não lançou erro, mas "
                "devolveu texto idêntico ao original (possível bloqueio/rate-limit silencioso "
                "do Google Translate, ou simplesmente não há o que traduzir)."
            )
            if attempts_no_error >= _MAX_ATTEMPTS_NO_ERROR:
                logger.debug(
                    f"'{prefix}{text:.80}' não mudou em {attempts_no_error} tentativa(s) sem "
                    "erro; provavelmente não há tradução a fazer (nome próprio, termo emprestado). "
                    "Mantendo original."
                )
                return text
        if attempt < _MAX_ATTEMPTS:
            time.sleep(attempt * 2)
    if error_page is not None:
        logger.warning(
            f"Google Translate devolveu a página de erro em vez de traduzir {prefix}'{text:.80}': "
            f"'{error_page:.80}'. Mantendo original."
        )
    logger.debug(
        f"Falha ao traduzir {prefix}'{text:.80}' após {_MAX_ATTEMPTS} tentativas "
        "com erro. Mantendo original."
    )
    return text
