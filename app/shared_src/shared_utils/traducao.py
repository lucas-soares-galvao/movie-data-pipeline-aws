"""traducao.py — Função compartilhada de tradução inglês → português."""

from __future__ import annotations

import logging
import time

from deep_translator import GoogleTranslator

logger = logging.getLogger()

_MAX_TENTATIVAS = 5


def traduzir_texto(texto: str, contexto: str = "") -> str:
    """
    Traduz texto de inglês para português via Google Translate.

    Faz até _MAX_TENTATIVAS tentativas com backoff entre elas, já que o
    endpoint não-oficial do Google Translate falha esporadicamente sob alto
    volume de chamadas paralelas. Retorna o texto original se todas as
    tentativas falharem, para não interromper o job.

    Args:
        texto:    Texto em inglês a ser traduzido.
        contexto: Descrição opcional do item traduzido (usada no log de warning).

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar.
    """
    if not texto:
        return ""
    prefixo = f"{contexto} " if contexto else ""
    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        try:
            return GoogleTranslator(source="en", target="pt").translate(texto)
        except Exception as exc:
            logger.debug(f"Tentativa {tentativa} de traduzir {prefixo}'{texto}' falhou: {exc}")
            if tentativa < _MAX_TENTATIVAS:
                time.sleep(tentativa * 2)
    logger.warning(
        f"Falha ao traduzir {prefixo}'{texto:.80}' após {_MAX_TENTATIVAS} tentativas. Mantendo original."
    )
    return texto
