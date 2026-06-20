# Importado como "lambda_lightsail_scheduler_main" (registrado no conftest.py)
# para evitar conflito com os outros main.py do projeto em sys.modules.

import os
from unittest.mock import MagicMock, patch

import pytest

import lambda_lightsail_scheduler_main as main


class TestLambdaHandler:

    def test_stop_chama_stop_instance(self):
        """Acao 'stop' deve chamar stop_instance com o nome da instancia do env."""
        mock_client = MagicMock()
        with patch("lambda_lightsail_scheduler_main.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            result = main.lambda_handler({"action": "stop"}, None)

        mock_client.stop_instance.assert_called_once_with(instanceName="test-instance")
        assert result == {"status": "stopping", "instance": "test-instance"}

    def test_start_chama_start_instance(self):
        """Acao 'start' deve chamar start_instance com o nome da instancia do env."""
        mock_client = MagicMock()
        with patch("lambda_lightsail_scheduler_main.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            result = main.lambda_handler({"action": "start"}, None)

        mock_client.start_instance.assert_called_once_with(instanceName="test-instance")
        assert result == {"status": "starting", "instance": "test-instance"}

    def test_acao_desconhecida_levanta_value_error(self):
        """Qualquer acao que nao seja 'start' ou 'stop' deve lancar ValueError."""
        with patch("lambda_lightsail_scheduler_main.boto3"):
            with pytest.raises(ValueError):
                main.lambda_handler({"action": "restart"}, None)

    def test_sem_instance_name_levanta_key_error(self):
        """Se LIGHTSAIL_INSTANCE_NAME nao estiver definida, deve lancar KeyError."""
        env_sem_nome = {k: v for k, v in os.environ.items() if k != "LIGHTSAIL_INSTANCE_NAME"}
        with (
            patch("lambda_lightsail_scheduler_main.boto3"),
            patch.dict(os.environ, env_sem_nome, clear=True),
        ):
            with pytest.raises(KeyError):
                main.lambda_handler({"action": "stop"}, None)
