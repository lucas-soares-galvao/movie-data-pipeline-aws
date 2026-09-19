import base64
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
# load_gmail_credentials/send_gmail_email — só a integração (utils.py reexporta
# de shared_utils.gmail_helpers); os casos de borda estão em
# test/shared_src/test_gmail_helpers.py. Não comparamos por identidade (is) com
# shared_utils.gmail_helpers aqui: test/conftest.py recarrega "shared_utils.*" a
# cada arquivo de teste de uma suite (isolamento entre suites Glue/Lambda), o que
# faria um import direto do módulo dentro do teste produzir um objeto novo — só o
# comportamento importa pra confirmar que o import em utils.py resolveu certo.
# ---------------------------------------------------------------------------


class TestGmailHelpersReexport:
    def test_send_gmail_email_reexportado_funciona_sem_credenciais(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.delenv("GMAIL_SENDER_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        assert send_gmail_email("user@ex.com", "Assunto", "Corpo") is False

    def test_load_gmail_credentials_reexportado_funciona_com_env_vars(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")

        assert load_gmail_credentials() == ("filmbot.lsgalvao@gmail.com", "senha-de-app")
