"""test_infrastructure.py — testes do bootstrap de processo e rate limiting do FilmBot."""

import time
from unittest.mock import patch

from src import infrastructure


class TestLoadFilmbotPassword:
    def test_retorna_sem_chamar_secrets_manager_quando_secret_arn_nao_configurado(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        with patch("src.infrastructure.boto3.client") as mock_client:
            infrastructure.load_filmbot_password()
        mock_client.assert_not_called()

    def test_retorna_sem_chamar_secrets_manager_quando_secrets_toml_ja_existe(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123456789012:secret:x")
        with (
            patch("src.infrastructure.Path.exists", return_value=True),
            patch("src.infrastructure.boto3.client") as mock_client,
        ):
            infrastructure.load_filmbot_password()
        mock_client.assert_not_called()


class TestSetupCloudwatchLogging:
    def test_retorna_sem_registrar_handler_quando_log_group_nao_configurado(self, monkeypatch):
        monkeypatch.delenv("CLOUDWATCH_LOG_GROUP", raising=False)
        infrastructure.setup_cloudwatch_logging.clear()
        with patch("src.infrastructure.watchtower.CloudWatchLogHandler") as mock_handler:
            infrastructure.setup_cloudwatch_logging()
        mock_handler.assert_not_called()


class TestGetClientIp:
    def test_retorna_local_quando_nao_ha_header_x_forwarded_for(self):
        assert infrastructure.get_client_ip() == "local"


class TestEventsInWindow:
    def test_conta_apenas_eventos_dentro_da_janela(self):
        agora = time.time()
        history = {"1.2.3.4": [agora - 10, agora - 3700]}

        resultado = infrastructure.events_in_window(history, "1.2.3.4", window_seconds=3600)

        assert resultado == 1

    def test_limpa_eventos_expirados_do_historico(self):
        agora = time.time()
        history = {"1.2.3.4": [agora - 10, agora - 3700]}

        infrastructure.events_in_window(history, "1.2.3.4", window_seconds=3600)

        assert history["1.2.3.4"] == [history["1.2.3.4"][0]]

    def test_retorna_zero_para_ip_sem_historico(self):
        assert infrastructure.events_in_window({}, "1.2.3.4", window_seconds=3600) == 0


class TestSecondsUntilAvailable:
    def test_retorna_zero_quando_nao_ha_historico(self):
        assert infrastructure.seconds_until_available({}, "1.2.3.4", window_seconds=60) == 0

    def test_calcula_segundos_restantes_ate_evento_mais_antigo_expirar(self):
        agora = time.time()
        history = {"1.2.3.4": [agora - 50]}

        resultado = infrastructure.seconds_until_available(history, "1.2.3.4", window_seconds=60)

        assert 9 <= resultado <= 10

    def test_retorna_zero_quando_janela_ja_expirou(self):
        agora = time.time()
        history = {"1.2.3.4": [agora - 120]}

        assert infrastructure.seconds_until_available(history, "1.2.3.4", window_seconds=60) == 0
