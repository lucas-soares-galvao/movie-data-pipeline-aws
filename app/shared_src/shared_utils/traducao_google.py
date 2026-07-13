"""traducao_google.py — Tradução para português via Google Translate (deep_translator)."""

from __future__ import annotations

import logging
import time

from deep_translator import GoogleTranslator

logger = logging.getLogger()

_MAX_TENTATIVAS = 5
_MAX_TENTATIVAS_SEM_ERRO = 2


def traduzir_texto(texto: str, contexto: str = "") -> str:
    """
    Traduz texto para português via Google Translate, detectando automaticamente
    o idioma de origem (source="auto").

    Faz até _MAX_TENTATIVAS tentativas com backoff entre elas, já que o
    endpoint não-oficial do Google Translate falha esporadicamente sob alto
    volume de chamadas paralelas. Duas formas de falha contam como tentativa
    malsucedida:
      - a chamada lançar exceção — tende a ser transitório (rede, rate limit),
        por isso usa o orçamento completo de _MAX_TENTATIVAS;
      - retornar normalmente um texto idêntico ao original — na maioria das
        vezes indica que não há o que traduzir (nome próprio, termo
        emprestado como "anime"/"hotel"), não bloqueio transitório, por isso
        desiste mais cedo (_MAX_TENTATIVAS_SEM_ERRO).
    Retorna o texto original se todas as tentativas aplicáveis se esgotarem,
    para não interromper o job.

    Args:
        texto:    Texto a ser traduzido (idioma de origem detectado automaticamente).
        contexto: Descrição opcional do item traduzido (usada no log).

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar.
    """
    if not texto:
        return ""
    prefixo = f"{contexto} " if contexto else ""
    tentativas_sem_erro = 0
    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        try:
            resultado = GoogleTranslator(source="auto", target="pt").translate(texto)
        except Exception as exc:
            logger.debug(f"Tentativa {tentativa} de traduzir {prefixo}'{texto}' falhou: {exc}")
        else:
            if resultado and resultado != texto:
                return resultado
            tentativas_sem_erro += 1
            logger.debug(
                f"Tentativa {tentativa} de traduzir {prefixo}'{texto:.80}' não lançou erro, mas "
                "devolveu texto idêntico ao original (possível bloqueio/rate-limit silencioso "
                "do Google Translate, ou simplesmente não há o que traduzir)."
            )
            if tentativas_sem_erro >= _MAX_TENTATIVAS_SEM_ERRO:
                logger.debug(
                    f"'{prefixo}{texto:.80}' não mudou em {tentativas_sem_erro} tentativa(s) sem "
                    "erro; provavelmente não há tradução a fazer (nome próprio, termo emprestado). "
                    "Mantendo original."
                )
                return texto
        if tentativa < _MAX_TENTATIVAS:
            time.sleep(tentativa * 2)
    logger.warning(
        f"Falha ao traduzir {prefixo}'{texto:.80}' após {_MAX_TENTATIVAS} tentativas "
        "com erro. Mantendo original."
    )
    return texto
