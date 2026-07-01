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


def _calcular_espera(attempt: int, response=None) -> float:
    """Backoff exponencial com jitter. Respeita Retry-After em 429."""
    # Para 429, o servidor pode informar no header "Retry-After" quanto tempo esperar.
    # Para os demais erros, usa backoff exponencial (1s → 2s → 4s).
    # random.uniform(0, 1) adiciona um "jitter" (variação aleatória) de até 1s
    # para evitar que múltiplos workers acordem exatamente ao mesmo tempo.
    if response is not None and response.status_code == 429 and "Retry-After" in response.headers:
        return int(response.headers["Retry-After"]) + random.uniform(0, 1)
    return (2 ** attempt) + random.uniform(0, 1)


def api_get(url: str, params: dict, max_retries: int = 5) -> dict:
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
        eh_ultima_tentativa = attempt == max_retries - 1
        wait: float
        try:
            # timeout=30 evita que o job fique preso esperando por uma resposta
            # que nunca chega (servidor travado, rede lenta, etc.)
            response = requests.get(url, params=params, timeout=30)

            if response.status_code not in _TRANSIENT_HTTP_CODES:
                # Status não é transiente: raise_for_status() lança exceção para 4xx/5xx
                # permanentes (ex: 401, 404). Para 200 OK, não faz nada e retorna o JSON.
                response.raise_for_status()
                return response.json()

            if eh_ultima_tentativa:
                logger.error(
                    f"HTTP {response.status_code} após {max_retries} tentativas. "
                    f"Todas as tentativas esgotadas para {url}."
                )
                response.raise_for_status()

            wait = _calcular_espera(attempt, response)

        except (ConnectionError, Timeout) as e:
            # Erros de rede (sem conexão, timeout) também merecem retry.
            if eh_ultima_tentativa:
                logger.error(
                    f"Erro de conexão após {max_retries} tentativas: {e}. "
                    f"Todas as tentativas esgotadas para {url}."
                )
                raise
            wait = _calcular_espera(attempt)

        logger.warning(
            f"Tentativa {attempt + 1}/{max_retries} falhou. Aguardando {wait:.1f}s..."
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
