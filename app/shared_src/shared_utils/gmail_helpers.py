"""gmail_helpers.py — Credenciais e envio de e-mail via Gmail/SMTP.

Compartilhado entre app/lambda_cognito_email_sender (trigger CustomEmailSender do
Cognito) e app/lightsail_ia (notificação de aprovação/reprovação/revogação de acesso,
ver src/infrastructure.py) — mesma lógica de credenciais e envio nos dois, só o
assunto/corpo do e-mail muda por chamador.
"""

import json
import logging
import os
import smtplib
from email.mime.text import MIMEText

import boto3

logger = logging.getLogger(__name__)

# timeout no SMTP: sem timeout explícito, uma conexão que aceita o TCP mas trava no
# handshake fica presa indefinidamente (o smtplib não tem timeout default) — trava a
# invocação da Lambda até o limite dela, ou a thread do processo Streamlit no Lightsail.
_SMTP_TIMEOUT_SECONDS = 10


def load_gmail_credentials() -> tuple[str, str] | None:
    """Busca remetente + senha de app do Gmail: do FILMBOT_SECRET_ARN (chaves
    gmail_sender_email/gmail_app_password) em produção, ou das env vars
    GMAIL_SENDER_EMAIL/GMAIL_APP_PASSWORD como fallback de dev local. Retorna None se
    nenhuma das duas fontes tiver as duas credenciais."""
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if secret_arn:
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "sa-east-1"))
        response = client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response["SecretString"])
        sender_email = secret.get("gmail_sender_email")
        app_password = secret.get("gmail_app_password")
        if sender_email and app_password:
            return sender_email, app_password

    sender_email = os.getenv("GMAIL_SENDER_EMAIL")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    if sender_email and app_password:
        return sender_email, app_password
    return None


def send_gmail_email(to_email: str, subject: str, body: str) -> bool:
    """Monta e envia (via Gmail/SMTP) um e-mail de texto puro. Retorna se o envio teve
    sucesso.

    Uma falha aqui (credencial errada, Gmail fora do ar) só é logada e reportada de
    volta pro retorno — nunca lançada — porque nenhum dos dois chamadores pode deixar
    isso derrubar uma ação que já aconteceu antes desta chamada (Cognito já processou o
    trigger; admin.py já aplicou a decisão de aprovar/reprovar/revogar)."""
    credentials = load_gmail_credentials()
    if credentials is None:
        logger.warning("Credenciais do Gmail não configuradas — e-mail não enviado para '%s'.", to_email)
        return False
    sender_email, app_password = credentials

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=_SMTP_TIMEOUT_SECONDS) as server:
            server.login(sender_email, app_password)
            server.send_message(message)
    except Exception:  # falha ao enviar não deve propagar pro chamador
        logger.exception("Falha ao enviar e-mail para '%s'", to_email)
        return False
    else:
        logger.info("E-mail enviado para '%s' (assunto: '%s').", to_email, subject)
        return True
