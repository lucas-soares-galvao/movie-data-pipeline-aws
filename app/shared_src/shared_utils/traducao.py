"""traducao.py — Função compartilhada de tradução inglês → português."""

from __future__ import annotations

import logging

from deep_translator import GoogleTranslator

logger = logging.getLogger()


def traduzir_texto(texto: str, contexto: str = "") -> str:
    """
    Traduz texto de inglês para português via Google Translate.

    Retorna o texto original em caso de qualquer falha (rede, rate limit,
    resposta vazia) para não interromper o job.

    Args:
        texto:    Texto em inglês a ser traduzido.
        contexto: Descrição opcional do item traduzido (usada no log de warning).

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar.
    """
    if not texto:
        return ""
    try:
        return GoogleTranslator(source="en", target="pt").translate(texto)
    except Exception as exc:
        prefixo = f"{contexto} " if contexto else ""
        logger.warning(f"Falha ao traduzir {prefixo}'{texto}': {exc}. Mantendo original.")
        return texto
