"""idioma_aws.py — Detecção de idioma via AWS Comprehend (boto3), usada como fallback
do langdetect (ver shared_utils.idioma)."""

from __future__ import annotations

import logging
from typing import Optional

import boto3

logger = logging.getLogger()


def detect_language_aws(text: str, region: str = "us-east-1") -> Optional[str]:
    """
    Detecta o idioma (código ISO 639-1) de um texto via AWS Comprehend (DetectDominantLanguage).

    Nunca lança exceção — devolve None em qualquer erro, para não interromper o job.
    A permissão IAM comprehend:DetectDominantLanguage já é concedida à role dos jobs que
    usam AWS Translate (o próprio Translate a aciona internamente via
    SourceLanguageCode="auto" — ver traducao_aws.py), então nenhuma mudança de IAM é
    necessária para esta chamada direta ao Comprehend.

    Args:
        text:   Texto a ter o idioma detectado.
        region: Região AWS do cliente do Comprehend. Comprehend não está disponível
                em sa-east-1 (região principal do pipeline), por isso o default é
                us-east-1 — a chamada é stateless, então usar outra região não tem
                custo de localidade.

    Returns:
        Código ISO 639-1 do idioma de maior confiança (`Score`) detectado pelo
        Comprehend, ou None se o texto for vazio ou a chamada falhar.
    """
    if not text or not text.strip():
        return None
    try:
        client = boto3.client("comprehend", region_name=region)
        response = client.detect_dominant_language(Text=text)
        languages = response.get("Languages", [])
        if not languages:
            return None
        best = max(languages, key=lambda lang: lang.get("Score", 0))
        return best.get("LanguageCode")
    except Exception as exc:
        logger.warning(f"Falha ao detectar idioma via AWS Comprehend de '{text[:80]}': {exc}")
        return None
