"""
test_main.py — Testes unitários do Lambda lightsail_scheduler.

Testa a função lambda_handler() de main.py, que recebe um evento com a
chave "action" e inicia ou para a instância Lightsail via boto3.

O módulo é importado como "lambda_lightsail_scheduler_main" (nome único
registrado no conftest.py) para evitar conflito com os outros main.py do
projeto (lambda_api, glue_etl, etc.) que compartilham o mesmo sys.modules.

  test_stop_chama_stop_instance        → action="stop" chama stop_instance e retorna status correto
  test_start_chama_start_instance      → action="start" chama start_instance e retorna status correto
  test_acao_desconhecida_levanta_value_error → action inválida levanta ValueError
  test_sem_instance_name_levanta_key_error  → env var ausente levanta KeyError
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import lambda_lightsail_scheduler_main as main


class TestLambdaHandler(unittest.TestCase):

    @patch("lambda_lightsail_scheduler_main.boto3")
    def test_stop_chama_stop_instance(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        result = main.lambda_handler({"action": "stop"}, None)

        mock_client.stop_instance.assert_called_once_with(instanceName="test-instance")
        self.assertEqual(result, {"status": "stopping", "instance": "test-instance"})

    @patch("lambda_lightsail_scheduler_main.boto3")
    def test_start_chama_start_instance(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        result = main.lambda_handler({"action": "start"}, None)

        mock_client.start_instance.assert_called_once_with(instanceName="test-instance")
        self.assertEqual(result, {"status": "starting", "instance": "test-instance"})

    @patch("lambda_lightsail_scheduler_main.boto3")
    def test_acao_desconhecida_levanta_value_error(self, mock_boto3):
        with self.assertRaises(ValueError):
            main.lambda_handler({"action": "restart"}, None)

    @patch("lambda_lightsail_scheduler_main.boto3")
    def test_sem_instance_name_levanta_key_error(self, mock_boto3):
        env_sem_nome = {k: v for k, v in os.environ.items() if k != "LIGHTSAIL_INSTANCE_NAME"}
        with patch.dict(os.environ, env_sem_nome, clear=True):
            with self.assertRaises(KeyError):
                main.lambda_handler({"action": "stop"}, None)


if __name__ == "__main__":
    unittest.main()
