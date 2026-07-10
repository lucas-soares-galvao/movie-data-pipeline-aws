"""traducao.py — Função compartilhada de tradução para português com detecção automática de idioma."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List

import pandas as pd
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


def traduzir_em_paralelo(
    valores: List[str], traduzir_fn: Callable[[str], str], max_workers: int = 10
) -> List[str]:
    """
    Aplica traduzir_fn a cada item de valores em paralelo via ThreadPoolExecutor.

    Recebe a função de tradução como parâmetro (em vez de chamar traduzir_texto
    diretamente) para que os chamadores continuem passando sua própria referência
    local de traduzir_texto — a mesma que seus testes fazem mock.

    Args:
        valores:     Textos a traduzir, na ordem em que devem ser retornados.
        traduzir_fn: Função chamada para cada item (ex.: traduzir_texto).
        max_workers: Número de threads concorrentes.

    Returns:
        Lista de textos traduzidos, na mesma ordem de valores.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(traduzir_fn, valores))


def elegivel_overview_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de overview: idioma original diferente de pt, com overview_en preenchido."""
    return (
        (df["original_language"] != "pt")
        & df["overview_en"].notna()
        & (df["overview_en"] != "")
    )


def elegivel_tagline_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de tagline: campo preenchido e idioma original diferente de pt."""
    return (
        df["tagline"].notna()
        & (df["tagline"] != "")
        & (df["original_language"] != "pt")
    )


def elegivel_keywords_pt(df: pd.DataFrame) -> "pd.Series[bool]":
    """Candidatos à tradução de keywords: campo preenchido e idioma original diferente de pt
    (evita reenviar ao Google Translate keywords que já podem estar em português)."""
    return (
        df["keywords"].notna()
        & (df["keywords"] != "")
        & (df["original_language"] != "pt")
    )
