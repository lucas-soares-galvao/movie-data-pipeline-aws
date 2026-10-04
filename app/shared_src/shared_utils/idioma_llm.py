"""idioma_llm.py — Detecção de idioma via LLM (OpenRouter, litellm)."""

from __future__ import annotations

import logging
import re

import litellm

from shared_utils.llm_metrics import EMPTY, INVALID, OK, record_call, record_failure
from shared_utils.traducao_llm import (
    _LLM_EXTRA_BODY,
    _LLM_FALLBACK_MODELS,  # noqa: F401 — reexportado só para os testes inspecionarem
    _LLM_MODEL,
    _LLM_NUM_RETRIES,
    _get_llm_api_key,
)

logger = logging.getLogger()

# Textos muito menores que tradução (só o código ISO 639-1 como saída).
_LLM_TIMEOUT_SECONDS = 10
_LLM_MAX_TOKENS = 10

_SYSTEM_PROMPT = (
    'Você é um detector de idioma. Devolva APENAS o código ISO 639-1 (duas letras '
    'minúsculas, ex.: "en", "pt", "es", "ja", "ko") do idioma predominante do texto '
    "do usuário. Não devolva nenhum outro texto, explicação ou pontuação."
)

_ISO_639_1_PATTERN = re.compile(r"^[a-z]{2}$")


def detect_language_llm(text: str) -> str | None:
    """
    Detecta o idioma (código ISO 639-1) de um texto via LLM (OpenRouter), com
    fallback nativo de modelo (extra_body.models) se o primário falhar.

    Reaproveita o modelo/chave/fallback já configurados em traducao_llm.py — mesmo
    padrão de import cruzado já existente entre idioma.py/traducao.py (evita
    duplicar a leitura do secret e a lista de fallback de modelo).

    Nunca lança exceção — devolve None em qualquer erro ou resposta fora do padrão
    ISO 639-1, para não interromper o job nem poluir detected_language_*_column com
    um valor inválido. Cada chamada (sucesso, vazia, inválida ou exceção) é registrada em
    shared_utils.llm_metrics para o resumo de uso/falhas/custo dos logs.

    Args:
        text: Texto a ter o idioma detectado.

    Returns:
        Código ISO 639-1 do idioma detectado, ou None se o texto for vazio, a
        chamada falhar, ou a resposta não for um código de 2 letras válido.
    """
    if not text or not text.strip():
        return None
    try:
        response = litellm.completion(
            model=_LLM_MODEL,
            api_key=_get_llm_api_key(),
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
            num_retries=_LLM_NUM_RETRIES,
            timeout=_LLM_TIMEOUT_SECONDS,
            max_tokens=_LLM_MAX_TOKENS,
            extra_body=_LLM_EXTRA_BODY,
        )
        content = response.choices[0].message.content
        if not content:
            record_call("detecção", response, text, EMPTY)
            return None
        code = content.strip().lower()
        if not _ISO_639_1_PATTERN.match(code):
            logger.warning(f"LLM devolveu código de idioma fora do padrão ISO 639-1 para '{text[:80]}': {content!r}")
            record_call("detecção", response, text, INVALID)
            return None
        record_call("detecção", response, text, OK)
        return code
    # Chamada de API externa, não pode derrubar o job.
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Falha ao detectar idioma via LLM de '{text[:80]}': {exc}")
        record_failure("detecção", exc, text)
        return None
