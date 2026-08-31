"""utils.py — Descriptografia do código do Cognito e envio via Gmail/SMTP."""

import base64
import json
import logging
import os
import smtplib
from email.mime.text import MIMEText
from typing import Any

import aws_encryption_sdk
import boto3
from aws_cryptographic_material_providers.mpl import AwsCryptographicMaterialProviders
from aws_cryptographic_material_providers.mpl.config import MaterialProvidersConfig
from aws_cryptographic_material_providers.mpl.models import CreateAwsKmsKeyringInput

# boto3 não tem stub de tipo para o cliente KMS; Any permite o type checker continuar sem erro.
KmsClient = Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# triggerSource do Cognito para os quais o FilmBot hoje envia e-mail — cadastro (primeiro
# código, efeito colateral do SignUp) e reenvio (ResendConfirmationCode) usam o mesmo texto.
# Os demais triggerSource possíveis (Authentication, UpdateUserAttribute, VerifyUserAttribute,
# AdminCreateUser, AccountTakeOverNotification) não correspondem a nenhum fluxo usado pelo
# projeto hoje (sem MFA por e-mail, sem alteração de e-mail própria, sem AdminCreateUser, sem
# detecção de risco configurada) — ver build_email_content.
_SIGNUP_TRIGGER_SOURCES = {"CustomEmailSender_SignUp", "CustomEmailSender_ResendCode"}


def decrypt_code(encrypted_code_b64: str, kms_key_arn: str, kms_client: KmsClient) -> str:
    """
    Descriptografa o código de verificação que o Cognito envia criptografado ao trigger
    CustomEmailSender (AWS Encryption SDK + KMS keyring) — ver
    https://docs.aws.amazon.com/encryption-sdk/latest/developer-guide/python-example-code.html.

    REQUIRE_ENCRYPT_ALLOW_DECRYPT (em vez do default REQUIRE_ENCRYPT_REQUIRE_DECRYPT) segue a
    própria política usada no exemplo oficial do Cognito para este trigger — mais permissiva na
    descriptografia, para não depender de qual algorithm suite o Cognito usou internamente.

    Args:
        encrypted_code_b64: `event["request"]["code"]` — string base64 recebida do Cognito.
        kms_key_arn:        ARN da chave KMS usada pelo Cognito para criptografar o código
                             (mesma chave configurada em `lambda_config.kms_key_id` do user pool).
        kms_client:         Cliente boto3 do KMS já instanciado.

    Returns:
        O código em texto plano.
    """
    client = aws_encryption_sdk.EncryptionSDKClient(
        commitment_policy=aws_encryption_sdk.CommitmentPolicy.REQUIRE_ENCRYPT_ALLOW_DECRYPT
    )
    material_providers = AwsCryptographicMaterialProviders(config=MaterialProvidersConfig())
    keyring = material_providers.create_aws_kms_keyring(
        input=CreateAwsKmsKeyringInput(kms_key_id=kms_key_arn, kms_client=kms_client)
    )

    plaintext_bytes, _header = client.decrypt(
        source=base64.b64decode(encrypted_code_b64), keyring=keyring
    )
    return plaintext_bytes.decode("utf-8")


def build_email_content(trigger_source: str, code: str | None) -> tuple[str, str] | None:
    """
    Monta (assunto, corpo) do e-mail para o `triggerSource` do Cognito, reaproveitando o texto
    que antes vivia em `verification_message_template` (infra/lightsail_ia.tf).

    Args:
        trigger_source: `event["triggerSource"]` — identifica qual fluxo do Cognito disparou o
                         trigger (ver _SIGNUP_TRIGGER_SOURCES acima).
        code:           Código em texto plano (retorno de decrypt_code), ou None se o evento não
                         trouxe `request.code` (não deveria acontecer para os triggerSource
                         tratados abaixo, mas o Cognito não garante isso contratualmente).

    Returns:
        Tupla (assunto, corpo), ou None se `trigger_source` não é um dos fluxos usados pelo
        FilmBot hoje — nesse caso o chamador deve apenas logar, sem enviar nada.
    """
    if trigger_source in _SIGNUP_TRIGGER_SOURCES:
        return "Confirme seu e-mail — FilmBot", f"Seu código de confirmação de cadastro no FilmBot é {code}"
    if trigger_source == "CustomEmailSender_ForgotPassword":
        return "Recuperação de senha — FilmBot", f"Seu código de recuperação de senha no FilmBot é {code}"
    return None


def load_gmail_credentials() -> tuple[str, str] | None:
    """Busca remetente + senha de app do Gmail: do FILMBOT_SECRET_ARN (chaves
    gmail_sender_email/gmail_app_password) em produção, ou das env vars
    GMAIL_SENDER_EMAIL/GMAIL_APP_PASSWORD como fallback de dev local — mesmo padrão de
    app/lightsail_ia/src/infrastructure.py::_load_gmail_credentials (duplicado aqui de propósito:
    a Lambda não tem acesso a shared_utils em runtime — só Lambda/Glue empacotam esse pacote via
    build_lambda_package.py/build_glue_wheel.py, o deploy do lightsail_ia não). Retorna None se
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
    """Monta e envia (via Gmail/SMTP) um e-mail de texto puro. Retorna se o envio teve sucesso.

    Uma falha aqui (credencial errada, Gmail fora do ar) só é logada, nunca lançada — o Cognito
    não espera nenhum retorno específico deste trigger (ver doc oficial do CustomEmailSender) e
    lançar aqui só faria o Cognito registrar uma invocação de Lambda com erro, sem nenhum
    benefício para o usuário."""
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
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.send_message(message)
    except Exception as exc:  # noqa: BLE001 — falha ao enviar não deve propagar pro Cognito
        logger.error("Falha ao enviar e-mail para '%s': %s", to_email, exc)
        return False
    else:
        logger.info("E-mail enviado para '%s' (assunto: '%s').", to_email, subject)
        return True
