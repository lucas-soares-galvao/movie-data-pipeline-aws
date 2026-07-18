"""idioma_langdetect.py — Detecção de idioma local via langdetect (offline, sem custo)."""

from __future__ import annotations

import logging
from typing import Optional

from langdetect import DetectorFactory, LangDetectException, detect

logger = logging.getLogger()

# langdetect usa amostragem probabilística de n-gramas internamente — sem seed fixo,
# o mesmo texto pode retornar idiomas diferentes entre execuções/testes.
DetectorFactory.seed = 0


def detect_language_langdetect(text: str) -> Optional[str]:
    """
    Detecta o idioma (código ISO 639-1) de um texto via langdetect.

    Nunca lança exceção — devolve None quando o texto é vazio, quando o langdetect
    não consegue detectar (comum em textos curtos ou sem sinal linguístico
    suficiente, ex.: keywords tipo "ação, suspense") ou em qualquer erro
    inesperado, para não interromper o job.

    Args:
        text: Texto a ter o idioma detectado.

    Returns:
        Código ISO 639-1 do idioma detectado (ex.: "en", "pt"), ou None se não
        for possível detectar.
    """
    if not text or not text.strip():
        return None
    try:
        return detect(text)
    except LangDetectException:
        return None
    except Exception as exc:
        logger.warning(f"Falha inesperada ao detectar idioma via langdetect de '{text[:80]}': {exc}")
        return None
