"""infrastructure.py — bootstrap de processo e utilitários de rate limiting do FilmBot."""

import json
import logging
import math
import os
import time
from pathlib import Path

import boto3
import streamlit as st
import watchtower


def load_filmbot_password() -> None:
    """Busca filmbot_password do Secrets Manager e escreve em secrets.toml."""
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if not secret_arn:
        return
    secrets_dir = Path(__file__).parent.parent / ".streamlit"
    secrets_file = secrets_dir / "secrets.toml"
    if secrets_file.exists():
        return
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "sa-east-1"))
    response = client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])
    secrets_dir.mkdir(exist_ok=True)
    secrets_file.write_text(
        f'[auth]\npassword = "{secret["filmbot_password"]}"\n',
        encoding="utf-8",
    )
    secrets_file.chmod(0o600)


@st.cache_resource
def setup_cloudwatch_logging() -> None:
    """Registra o handler de CloudWatch no root logger uma única vez por processo.

    O Streamlit reexecuta o script inteiro a cada rerun (clique, st.rerun(),
    etc.) — sem @st.cache_resource, este bloco rodaria a cada rerun e
    acumularia um CloudWatchLogHandler novo no root logger por vez (cada um
    com seu próprio cliente boto3, fila e thread de background), sem nunca
    remover os anteriores. Resultado: vazamento de memória progressivo e
    cada log duplicado uma vez por handler acumulado. Mesmo padrão de
    "roda uma vez por processo" já usado nas factories de histórico abaixo.
    """
    log_group = os.getenv("CLOUDWATCH_LOG_GROUP", "")
    if not log_group:
        return
    cw_handler = watchtower.CloudWatchLogHandler(
        log_group_name=log_group,
        boto3_client=boto3.client("logs", region_name=os.getenv("AWS_REGION", "sa-east-1")),
        create_log_group=False,
    )
    logging.root.addHandler(cw_handler)
    logging.root.setLevel(logging.ERROR)


def get_client_ip() -> str:
    """Extrai o IP do cliente a partir do header X-Forwarded-For repassado pelo Caddy."""
    # Confiar no primeiro valor só é seguro porque o Caddyfile sobrescreve X-Forwarded-For
    # (header_up) em vez de anexar — do contrário um cliente poderia forjar esse valor e
    # burlar o rate limit por IP abaixo.
    forwarded = st.context.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else "local"


def events_in_window(history: dict[str, list[float]], ip: str, window_seconds: int) -> int:
    """Conta eventos dentro da janela de tempo (em segundos) para o IP no histórico
    informado e limpa registros expirados. Reusada para consultas, transcrições
    e tentativas de login incorretas, cada uma com seu próprio dict de histórico."""
    now = time.time()
    filtered = [t for t in history.get(ip, []) if t > now - window_seconds]
    history[ip] = filtered
    return len(filtered)


def seconds_until_available(history: dict[str, list[float]], ip: str, window_seconds: int) -> int:
    """Calcula quantos segundos faltam até o evento mais antigo do IP expirar, na janela
    de tempo (em segundos) informada."""
    entries = history.get(ip, [])
    if not entries:
        return 0
    return max(0, math.ceil(entries[0] + window_seconds - time.time()))
