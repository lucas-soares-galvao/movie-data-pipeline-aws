import base64
import json
from unittest.mock import MagicMock, patch

import aws_encryption_sdk
from src.utils import (
    build_email_content,
    decrypt_code,
    load_gmail_credentials,
    send_gmail_email,
)

# ---------------------------------------------------------------------------
# decrypt_code
# ---------------------------------------------------------------------------


class TestDecryptCode:
    def test_decifra_o_codigo_usando_o_keyring_da_chave_informada(self):
        mock_kms_client = MagicMock()
        mock_keyring = MagicMock()
        mock_material_providers = MagicMock()
        mock_material_providers.create_aws_kms_keyring.return_value = mock_keyring
        ciphertext = b"codigo-criptografado"

        with (
            patch("src.utils.AwsCryptographicMaterialProviders", return_value=mock_material_providers),
            patch("src.utils.aws_encryption_sdk.EncryptionSDKClient") as mock_sdk_client_cls,
        ):
            mock_sdk_client = mock_sdk_client_cls.return_value
            mock_sdk_client.decrypt.return_value = (b"123456", MagicMock())

            resultado = decrypt_code(
                base64.b64encode(ciphertext).decode(),
                "arn:aws:kms:sa-east-1:123456789012:key/test-key-id",
                mock_kms_client,
            )

        assert resultado == "123456"
        mock_sdk_client_cls.assert_called_once_with(
            commitment_policy=aws_encryption_sdk.CommitmentPolicy.REQUIRE_ENCRYPT_ALLOW_DECRYPT
        )
        _, decrypt_kwargs = mock_sdk_client.decrypt.call_args
        assert decrypt_kwargs["source"] == ciphertext
        assert decrypt_kwargs["keyring"] == mock_keyring

    def test_cria_o_keyring_com_a_chave_e_o_cliente_kms_informados(self):
        mock_kms_client = MagicMock()
        mock_material_providers = MagicMock()
        mock_material_providers.create_aws_kms_keyring.return_value = MagicMock()

        with (
            patch("src.utils.AwsCryptographicMaterialProviders", return_value=mock_material_providers),
            patch("src.utils.aws_encryption_sdk.EncryptionSDKClient") as mock_sdk_client_cls,
        ):
            mock_sdk_client_cls.return_value.decrypt.return_value = (b"000000", MagicMock())
            decrypt_code(
                base64.b64encode(b"x").decode(),
                "arn:aws:kms:sa-east-1:123456789012:key/test-key-id",
                mock_kms_client,
            )

        _, keyring_kwargs = mock_material_providers.create_aws_kms_keyring.call_args
        keyring_input = keyring_kwargs["input"]
        assert keyring_input.kms_key_id == "arn:aws:kms:sa-east-1:123456789012:key/test-key-id"
        assert keyring_input.kms_client is mock_kms_client


# ---------------------------------------------------------------------------
# build_email_content
# ---------------------------------------------------------------------------


class TestBuildEmailContent:
    def test_sign_up_retorna_texto_de_confirmacao_de_cadastro(self):
        resultado = build_email_content("CustomEmailSender_SignUp", "123456")
        assert resultado is not None
        subject, body = resultado
        assert subject == "Confirme seu e-mail — FilmBot"
        assert "123456" in body

    def test_resend_code_usa_o_mesmo_texto_do_sign_up(self):
        resultado_signup = build_email_content("CustomEmailSender_SignUp", "111111")
        resultado_resend = build_email_content("CustomEmailSender_ResendCode", "111111")
        assert resultado_signup == resultado_resend

    def test_forgot_password_retorna_texto_de_recuperacao_de_senha(self):
        resultado = build_email_content("CustomEmailSender_ForgotPassword", "654321")
        assert resultado is not None
        subject, body = resultado
        assert subject == "Recuperação de senha — FilmBot"
        assert "654321" in body

    def test_trigger_source_nao_tratado_retorna_none(self):
        nao_tratados = [
            "CustomEmailSender_Authentication",
            "CustomEmailSender_UpdateUserAttribute",
            "CustomEmailSender_VerifyUserAttribute",
            "CustomEmailSender_AdminCreateUser",
            "CustomEmailSender_AccountTakeOverNotification",
        ]
        for trigger_source in nao_tratados:
            assert build_email_content(trigger_source, "000000") is None


# ---------------------------------------------------------------------------
# load_gmail_credentials
# ---------------------------------------------------------------------------


class TestLoadGmailCredentials:
    def test_busca_credenciais_do_secrets_manager(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123456789012:secret:x")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {"gmail_sender_email": "filmbot.lsgalvao@gmail.com", "gmail_app_password": "abcd efgh"}
            )
        }
        with patch("src.utils.boto3.client", return_value=mock_client):
            resultado = load_gmail_credentials()

        mock_client.get_secret_value.assert_called_once_with(
            SecretId="arn:aws:secretsmanager:sa-east-1:123456789012:secret:x"
        )
        assert resultado == ("filmbot.lsgalvao@gmail.com", "abcd efgh")

    def test_cai_para_fallback_de_env_vars_quando_secret_arn_nao_configurado(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")

        with patch("src.utils.boto3.client") as mock_boto:
            resultado = load_gmail_credentials()

        mock_boto.assert_not_called()
        assert resultado == ("filmbot.lsgalvao@gmail.com", "senha-de-app")

    def test_cai_para_fallback_quando_secret_nao_tem_as_chaves_gmail(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123456789012:secret:x")
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"llm_api_key": "sk-outra-coisa"})}

        with patch("src.utils.boto3.client", return_value=mock_client):
            resultado = load_gmail_credentials()

        assert resultado == ("filmbot.lsgalvao@gmail.com", "senha-de-app")

    def test_retorna_none_quando_nenhuma_credencial_esta_configurada(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.delenv("GMAIL_SENDER_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        assert load_gmail_credentials() is None


# ---------------------------------------------------------------------------
# send_gmail_email
# ---------------------------------------------------------------------------


class TestSendGmailEmail:
    def test_envia_email_com_sucesso(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")
        mock_smtp_server = MagicMock()

        with patch("src.utils.smtplib.SMTP_SSL") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp_server
            resultado = send_gmail_email("user@ex.com", "Assunto de teste", "Corpo do e-mail")

        mock_smtp.assert_called_once_with("smtp.gmail.com", 465)
        mock_smtp_server.login.assert_called_once_with("filmbot.lsgalvao@gmail.com", "senha-de-app")
        sent_message = mock_smtp_server.send_message.call_args[0][0]
        assert sent_message["Subject"] == "Assunto de teste"
        assert sent_message["From"] == "filmbot.lsgalvao@gmail.com"
        assert sent_message["To"] == "user@ex.com"
        assert resultado is True

    def test_retorna_false_sem_chamar_smtp_quando_nenhuma_credencial_esta_configurada(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.delenv("GMAIL_SENDER_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        with patch("src.utils.smtplib.SMTP_SSL") as mock_smtp:
            resultado = send_gmail_email("user@ex.com", "Assunto", "Corpo")

        mock_smtp.assert_not_called()
        assert resultado is False

    def test_loga_erro_sem_propagar_quando_smtp_falha(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")

        with patch("src.utils.smtplib.SMTP_SSL", side_effect=OSError("conexão recusada")):
            resultado = send_gmail_email("user@ex.com", "Assunto", "Corpo")

        assert resultado is False
