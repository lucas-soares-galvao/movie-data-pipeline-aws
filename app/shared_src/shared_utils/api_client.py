"""api_client.py — Funções compartilhadas para acesso a APIs externas."""

import json
import logging
import random
import time

import boto3
import requests
from requests.exceptions import ConnectionError, Timeout

logger = logging.getLogger()

# Códigos HTTP que indicam problema TEMPORÁRIO no servidor — vale tentar novamente.
# 429 = "Too Many Requests" (ultrapassou o rate limit da API)
# 5xx = erros internos do servidor (normalmente transitórios)
# Diferente de 401 (chave inválida) ou 404 (recurso não existe) — esses são erros
# permanentes que não melhoram com retry.
_TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}


def api_get(url: str, params: dict, max_retries: int = 3) -> dict:
    """
    GET com retry e backoff exponencial em erros transientes.

    Args:
        url:         URL completa do endpoint da API.
        params:      Parâmetros de query string.
        max_retries: Número máximo de tentativas antes de desistir.

    Returns:
        Dicionário Python com a resposta JSON da API.

    Raises:
        HTTPError: Se o servidor responder com erro não-transiente ou tentativas esgotadas.
        ConnectionError / Timeout: Se não conseguir conectar após max_retries tentativas.
    """
    for attempt in range(max_retries):
        is_last_attempt = attempt == max_retries - 1
        try:
            # timeout=30 evita que o job fique preso esperando por uma resposta
            # que nunca chega (servidor travado, rede lenta, etc.)
            response = requests.get(url, params=params, timeout=30)

            if response.status_code in _TRANSIENT_HTTP_CODES:
                if is_last_attempt:
                    logger.error(
                        f"HTTP {response.status_code} após {max_retries} tentativas. "
                        f"Todas as tentativas esgotadas para {url}."
                    )
                    response.raise_for_status()

                # Para 429, o servidor pode informar no header "Retry-After" quanto tempo esperar.
                # Para os demais erros transientes, usa backoff exponencial (1s → 2s → 4s).
                # random.uniform(0, 1) adiciona um "jitter" (variação aleatória) de até 1s
                # para evitar que múltiplos workers acordem exatamente ao mesmo tempo.
                if response.status_code == 429 and "Retry-After" in response.headers:
                    wait = int(response.headers["Retry-After"]) + random.uniform(0, 1)
                else:
                    wait = (2 ** attempt) + random.uniform(0, 1)

                logger.warning(
                    f"HTTP {response.status_code} (tentativa {attempt + 1}/{max_retries}). "
                    f"Aguardando {wait:.1f}s..."
                )
                time.sleep(wait)
                continue

            # Se chegou aqui, o status não é transiente — raise_for_status() lança exceção
            # para qualquer outro erro 4xx/5xx (ex: 401, 404). Para 200 OK retorna normalmente.
            response.raise_for_status()
            return response.json()

        except (ConnectionError, Timeout) as e:
            # Erros de rede (sem conexão, timeout) também merecem retry.
            if is_last_attempt:
                logger.error(
                    f"Erro de conexão após {max_retries} tentativas: {e}. "
                    f"Todas as tentativas esgotadas para {url}."
                )
                raise
            wait = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(
                f"Erro de conexão (tentativa {attempt + 1}/{max_retries}): {e}. "
                f"Aguardando {wait:.1f}s..."
            )
            time.sleep(wait)


def get_api_secret(secret_arn: str, key_name: str) -> str:
    """
    Busca um segredo no Secrets Manager.

    Formato esperado do segredo: {key_name: "valor"}

    Args:
        secret_arn: ARN completo do segredo no Secrets Manager.
        key_name:   Nome da chave dentro do JSON do segredo.

    Returns:
        O valor do segredo como string.
    """
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])
    return secret[key_name]
