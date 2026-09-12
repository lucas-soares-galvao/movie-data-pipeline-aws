"""
Lambda do trigger CustomEmailSender do Cognito — intercepta o código de verificação de
cadastro/reenvio/recuperação de senha do FilmBot e o envia pelo Gmail (mesmo remetente já usado
para as notificações do admin), em vez do domínio nativo compartilhado do Cognito, que cai quase
sempre em spam.
"""

import logging
import os
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from src.utils import build_email_content, decrypt_code, send_gmail_email

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Variável de ambiente injetada pelo Terraform (lambda_cognito_email_sender.tf, bloco
# environment da aws_lambda_function — mesma chave configurada em lambda_config.kms_key_id do
# user pool, ver infra/lightsail_ia.tf).
KMS_KEY_ARN = os.environ["KMS_KEY_ARN"]

# Timeout explícito no cliente KMS: decrypt_code roda dentro de Lambda (trigger
# CustomEmailSender), onde uma chamada ao KMS sem timeout pode pendurar a execução
# até o limite da função. O default do botocore (60s de connect/read) é longo demais.
_KMS_BOTO_CONFIG = BotoConfig(connect_timeout=5, read_timeout=10, retries={"max_attempts": 3})


def lambda_handler(event: dict[str, Any], context: Any) -> None:
    """
    Handler do trigger CustomEmailSender — payload definido pelo próprio Cognito, ver
    app/lambda_cognito_email_sender/lambda_cognito_email_sender.md.

    O Cognito não espera nenhum retorno específico deste trigger (ver doc oficial) — o handler
    só tem efeito colateral (enviar ou não o e-mail).
    """
    trigger_source = event["triggerSource"]
    user_attributes = event["request"]["userAttributes"]
    encrypted_code = event["request"].get("code")

    plaintext_code = None
    if encrypted_code:
        kms_client = boto3.client(
            "kms",
            region_name=os.getenv("AWS_REGION", "sa-east-1"),
            config=_KMS_BOTO_CONFIG,
        )
        plaintext_code = decrypt_code(encrypted_code, KMS_KEY_ARN, kms_client)

    content = build_email_content(trigger_source, plaintext_code)
    if content is None:
        logger.info("triggerSource '%s' não é tratado pelo FilmBot — nenhum e-mail enviado.", trigger_source)
        return

    subject, body = content
    send_gmail_email(user_attributes["email"], subject, body)
