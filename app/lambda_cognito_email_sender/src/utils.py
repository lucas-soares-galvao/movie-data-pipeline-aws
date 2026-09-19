"""utils.py — Descriptografia do código do Cognito e envio via Gmail/SMTP."""

import base64
from typing import Any

import aws_encryption_sdk
from aws_cryptographic_material_providers.mpl import AwsCryptographicMaterialProviders
from aws_cryptographic_material_providers.mpl.config import MaterialProvidersConfig
from aws_cryptographic_material_providers.mpl.models import CreateAwsKmsKeyringInput
from shared_utils.gmail_helpers import load_gmail_credentials, send_gmail_email

__all__ = [
    "decrypt_code",
    "build_email_content",
    "load_gmail_credentials",
    "send_gmail_email",
]

# boto3 não tem stub de tipo para o cliente KMS; Any permite o type checker continuar sem erro.
KmsClient = Any

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
