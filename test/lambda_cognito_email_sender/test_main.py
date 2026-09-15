import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("KMS_KEY_ARN", "arn:aws:kms:sa-east-1:123456789012:key/test-key-id")

# main.py cria o cliente boto3 (kms) no nível de módulo (python:S6243 — evita recriar a
# conexão a cada invocation "quente" da Lambda). Isso faz `import main` chamar boto3.client()
# de verdade; mockar aqui evita depender de credenciais AWS resolvíveis no ambiente onde o
# teste roda (máquina local, CI). Os testes sempre re-mockam main.kms_client por fora, então
# o mock usado só neste import nunca é observado.
with patch("boto3.client"):
    import main

EVENTO_SIGN_UP = {
    "triggerSource": "CustomEmailSender_SignUp",
    "request": {
        "code": "Y29kaWdvLWNyaXB0b2dyYWZhZG8=",
        "userAttributes": {"email": "user@ex.com", "name": "Fulano"},
    },
}


class TestLambdaHandler:
    def test_descriptografa_e_envia_email_para_sign_up(self):
        with (
            patch("main.kms_client") as mock_kms_client,
            patch("main.decrypt_code", return_value="123456") as mock_decrypt,
            patch("main.send_gmail_email", return_value=True) as mock_send,
        ):
            main.lambda_handler(EVENTO_SIGN_UP, MagicMock())

        mock_decrypt.assert_called_once_with(
            "Y29kaWdvLWNyaXB0b2dyYWZhZG8=", main.KMS_KEY_ARN, mock_kms_client
        )
        mock_send.assert_called_once()
        to_email, subject, body = mock_send.call_args[0]
        assert to_email == "user@ex.com"
        assert subject == "Confirme seu e-mail — FilmBot"
        assert "123456" in body

    def test_kms_client_configurado_com_timeout_explicito(self):
        # config= passado por timeout explícito do KMS (S7618) — evita que a chamada
        # pendure a Lambda até o limite da função.
        assert main._KMS_BOTO_CONFIG.connect_timeout == 5
        assert main._KMS_BOTO_CONFIG.read_timeout == 10

    def test_resend_code_usa_o_mesmo_texto_do_sign_up(self):
        evento = {**EVENTO_SIGN_UP, "triggerSource": "CustomEmailSender_ResendCode"}
        with (
            patch("main.kms_client"),
            patch("main.decrypt_code", return_value="123456"),
            patch("main.send_gmail_email", return_value=True) as mock_send,
        ):
            main.lambda_handler(evento, MagicMock())

        _, subject, body = mock_send.call_args[0]
        assert subject == "Confirme seu e-mail — FilmBot"
        assert "123456" in body

    def test_forgot_password_envia_texto_de_recuperacao(self):
        evento = {**EVENTO_SIGN_UP, "triggerSource": "CustomEmailSender_ForgotPassword"}
        with (
            patch("main.kms_client"),
            patch("main.decrypt_code", return_value="654321"),
            patch("main.send_gmail_email", return_value=True) as mock_send,
        ):
            main.lambda_handler(evento, MagicMock())

        _, subject, body = mock_send.call_args[0]
        assert subject == "Recuperação de senha — FilmBot"
        assert "654321" in body

    def test_trigger_source_nao_tratado_nao_envia_email(self):
        evento = {**EVENTO_SIGN_UP, "triggerSource": "CustomEmailSender_Authentication"}
        with (
            patch("main.kms_client"),
            patch("main.decrypt_code", return_value="000000"),
            patch("main.send_gmail_email") as mock_send,
        ):
            main.lambda_handler(evento, MagicMock())

        mock_send.assert_not_called()

    def test_nao_descriptografa_quando_evento_nao_traz_code(self):
        evento = {
            "triggerSource": "CustomEmailSender_AdminCreateUser",
            "request": {"userAttributes": {"email": "user@ex.com"}},
        }
        with (
            patch("main.kms_client"),
            patch("main.decrypt_code") as mock_decrypt,
            patch("main.send_gmail_email") as mock_send,
        ):
            main.lambda_handler(evento, MagicMock())

        mock_decrypt.assert_not_called()
        mock_send.assert_not_called()
