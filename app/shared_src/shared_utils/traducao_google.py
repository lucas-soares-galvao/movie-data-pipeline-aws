"""traducao_google.py — Tradução para português via Google Translate (deep_translator)."""

from __future__ import annotations

import logging
import time

from deep_translator import GoogleTranslator

logger = logging.getLogger()

_MAX_ATTEMPTS = 5
_MAX_ATTEMPTS_NO_ERROR = 2


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
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            result = GoogleTranslator(source="auto", target="pt").translate(text)
        except Exception as exc:
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
    logger.warning(
        f"Falha ao traduzir {prefix}'{text:.80}' após {_MAX_ATTEMPTS} tentativas "
        "com erro. Mantendo original."
    )
    return text
