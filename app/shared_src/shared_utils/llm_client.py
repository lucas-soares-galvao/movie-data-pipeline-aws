"""llm_client.py — Carregamento compartilhado da chave de API do LLM (OpenRouter),
usada tanto pelo agente de recomendação (lightsail_ia) quanto pela tradução/detecção
de idioma via LLM (traducao_llm.py/idioma_llm.py)."""

from __future__ import annotations

import json
import os

import boto3

from shared_utils.secret_redaction import register_secret

__all__ = ["load_llm_api_key"]


def load_llm_api_key(
    secret_field: str,
    env_var: str,
    region: str = "sa-east-1",
    required: bool = True,
) -> str | None:
    """
    Busca uma chave de API de LLM do Secrets Manager (produção) ou de uma variável de
    ambiente (desenvolvimento local).

    Em produção, FILMBOT_SECRET_ARN aponta para o secret unificado (tmdb_api_key,
    llm_api_key, transcription_api_key, filmbot_password) — o mesmo secret já lido por
    lambda_api, lambda_cognito_email_sender e lightsail_ia. secret_field indexa qual
    campo buscar dentro desse JSON; diferentes chamadores (agente de recomendação,
    tradução via LLM) reaproveitam o mesmo secret sem duplicar a lógica de busca.

    Args:
        secret_field: Nome do campo dentro do secret (ex.: "llm_api_key").
        env_var:      Nome da variável de ambiente usada como fallback em dev local, ou
                      quando FILMBOT_SECRET_ARN não está definida.
        region:       Região do Secrets Manager.
        required:     Se True, indexação direta — levanta KeyError quando secret_field
                      está ausente do secret (campo obrigatório, ex.: "llm_api_key").
                      Se False, usa .get() e devolve None quando ausente (campo
                      opcional, ex.: "transcription_api_key", adicionado ao secret
                      depois que ele já existia em produção) — permite que o chamador
                      suba normalmente antes do operador popular o campo.

    Returns:
        O valor da chave, ou None quando não encontrada (só possível com
        required=False, ou quando nem FILMBOT_SECRET_ARN nem env_var estão
        definidas).
    """
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if secret_arn:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response["SecretString"])
        value = secret[secret_field] if required else secret.get(secret_field)
    else:
        value = os.getenv(env_var)
    # Mascara o valor onde quer que apareça em logs/exceções (ver shared_utils.secret_redaction).
    register_secret(value)
    return value
