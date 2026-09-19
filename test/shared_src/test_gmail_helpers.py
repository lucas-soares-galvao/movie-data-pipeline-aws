"""
Testa shared_utils/gmail_helpers.py — credenciais e envio de e-mail via Gmail/SMTP,
compartilhado entre app/lambda_cognito_email_sender e app/lightsail_ia (ver
docstring do módulo). Os testes de integração de cada chamador (que o e-mail certo é
montado e enviado) continuam em test/lambda_cognito_email_sender/test_main.py e
test/lightsail_ia/test_infrastructure.py — aqui cobre só load_gmail_credentials/
send_gmail_email em si.
"""

import json
from unittest.mock import MagicMock, patch

from shared_utils.gmail_helpers import (
    _SMTP_TIMEOUT_SECONDS,
    load_gmail_credentials,
    send_gmail_email,
)

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
        with patch("shared_utils.gmail_helpers.boto3.client", return_value=mock_client):
            resultado = load_gmail_credentials()

        mock_client.get_secret_value.assert_called_once_with(
            SecretId="arn:aws:secretsmanager:sa-east-1:123456789012:secret:x"
        )
        assert resultado == ("filmbot.lsgalvao@gmail.com", "abcd efgh")

    def test_cai_para_fallback_de_env_vars_quando_secret_arn_nao_configurado(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")

        with patch("shared_utils.gmail_helpers.boto3.client") as mock_boto:
            resultado = load_gmail_credentials()

        mock_boto.assert_not_called()
        assert resultado == ("filmbot.lsgalvao@gmail.com", "senha-de-app")

    def test_cai_para_fallback_quando_secret_nao_tem_as_chaves_gmail(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123456789012:secret:x")
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"llm_api_key": "sk-outra-coisa"})}

        with patch("shared_utils.gmail_helpers.boto3.client", return_value=mock_client):
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

        with patch("shared_utils.gmail_helpers.smtplib.SMTP_SSL") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp_server
            resultado = send_gmail_email("user@ex.com", "Assunto de teste", "Corpo do e-mail")

        mock_smtp.assert_called_once_with("smtp.gmail.com", 465, timeout=_SMTP_TIMEOUT_SECONDS)
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

        with patch("shared_utils.gmail_helpers.smtplib.SMTP_SSL") as mock_smtp:
            resultado = send_gmail_email("user@ex.com", "Assunto", "Corpo")

        mock_smtp.assert_not_called()
        assert resultado is False

    def test_loga_erro_sem_propagar_quando_smtp_falha(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")

        with patch("shared_utils.gmail_helpers.smtplib.SMTP_SSL", side_effect=OSError("conexão recusada")):
            resultado = send_gmail_email("user@ex.com", "Assunto", "Corpo")

        assert resultado is False
