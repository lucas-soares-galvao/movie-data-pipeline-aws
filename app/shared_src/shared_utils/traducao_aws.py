"""traducao_aws.py — Tradução para português via AWS Translate (boto3)."""

from __future__ import annotations

import logging

import boto3

logger = logging.getLogger()


def traduzir_texto_aws(texto: str, region: str = "us-east-1") -> str:
    """
    Traduz texto para português via AWS Translate (detecção automática de idioma).

    Diferente de traduzir_texto (Google), não implementa retry manual: o AWS
    Translate é uma API oficial (sem o comportamento de bloqueio silencioso do
    endpoint não-oficial do Google Translate) e o cliente boto3 já reaplica
    retry em erros transitórios por padrão. Nunca lança exceção — devolve o
    texto original em caso de erro, para não interromper o job.

    Args:
        texto:  Texto a ser traduzido (idioma de origem detectado automaticamente).
        region: Região AWS do cliente do Translate. AWS Translate não está disponível
                em sa-east-1 (região principal do pipeline), por isso o default é
                us-east-1 — a chamada é stateless, então usar outra região não tem
                custo de localidade.

    Returns:
        Texto traduzido para português, ou o texto original se a tradução falhar.
    """
    try:
        cliente = boto3.client("translate", region_name=region)
        resposta = cliente.translate_text(
            Text=texto, SourceLanguageCode="auto", TargetLanguageCode="pt",
        )
        traduzido = resposta.get("TranslatedText", "").strip()
        if traduzido:
            return traduzido
    except Exception as exc:
        logger.warning(f"Falha ao traduzir via AWS Translate '{texto:.80}': {exc}")
    return texto
