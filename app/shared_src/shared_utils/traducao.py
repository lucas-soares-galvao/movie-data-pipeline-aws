"""traducao.py — Função compartilhada de tradução para português com detecção automática de idioma."""

from __future__ import annotations

import logging
import time

from deep_translator import GoogleTranslator

logger = logging.getLogger()

_MAX_TENTATIVAS = 5


def traduzir_texto(texto: str, contexto: str = "") -> str:
    """
    Traduz texto para português via Google Translate, detectando automaticamente
    o idioma de origem (source="auto").

    Faz até _MAX_TENTATIVAS tentativas com backoff entre elas, já que o
    endpoint não-oficial do Google Translate falha esporadicamente sob alto
    volume de chamadas paralelas. Duas formas de falha contam como tentativa
    malsucedida: a chamada lançar exceção, ou retornar normalmente um texto
    idêntico ao original (bloqueio/rate-limit silencioso do endpoint, que não
    é sinalizado como erro). Retorna o texto original se todas as tentativas
    falharem, para não interromper o job.

    Args:
        texto:    Texto a ser traduzido (idioma de origem detectado automaticamente).
        contexto: Descrição opcional do item traduzido (usada no log de warning).

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar.
    """
    if not texto:
        return ""
    prefixo = f"{contexto} " if contexto else ""
    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        try:
            resultado = GoogleTranslator(source="auto", target="pt").translate(texto)
        except Exception as exc:
            logger.debug(f"Tentativa {tentativa} de traduzir {prefixo}'{texto}' falhou: {exc}")
        else:
            if resultado and resultado != texto:
                return resultado
            logger.debug(
                f"Tentativa {tentativa} de traduzir {prefixo}'{texto:.80}' não lançou erro, mas "
                "devolveu texto idêntico ao original (possível bloqueio/rate-limit silencioso "
                "do Google Translate)."
            )
        if tentativa < _MAX_TENTATIVAS:
            time.sleep(tentativa * 2)
    logger.warning(
        f"Falha ao traduzir {prefixo}'{texto:.80}' após {_MAX_TENTATIVAS} tentativas "
        "(erro ou resposta idêntica ao original em todas elas). Mantendo original."
    )
    return texto
