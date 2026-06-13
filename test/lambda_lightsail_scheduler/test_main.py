# Importado como "lambda_lightsail_scheduler_main" (registrado no conftest.py)
# para evitar conflito com os outros main.py do projeto em sys.modules.

import os
import unittest
from unittest.mock import MagicMock, patch

import lambda_lightsail_scheduler_main as main


class TestLambdaHandler(unittest.TestCase):

    @patch("lambda_lightsail_scheduler_main.boto3")
    def test_stop_chama_stop_instance(self, mock_boto3):
        """Ação 'stop' deve chamar stop_instance com o nome da instância do env."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        result = main.lambda_handler({"action": "stop"}, None)

        mock_client.stop_instance.assert_called_once_with(instanceName="test-instance")
        self.assertEqual(result, {"status": "stopping", "instance": "test-instance"})

    @patch("lambda_lightsail_scheduler_main.boto3")
    def test_start_chama_start_instance(self, mock_boto3):
        """Ação 'start' deve chamar start_instance com o nome da instância do env."""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        result = main.lambda_handler({"action": "start"}, None)

        mock_client.start_instance.assert_called_once_with(instanceName="test-instance")
        self.assertEqual(result, {"status": "starting", "instance": "test-instance"})

    @patch("lambda_lightsail_scheduler_main.boto3")
    def test_acao_desconhecida_levanta_value_error(self, mock_boto3):
        """Qualquer ação que não seja 'start' ou 'stop' deve lançar ValueError."""
        with self.assertRaises(ValueError):
            main.lambda_handler({"action": "restart"}, None)

    @patch("lambda_lightsail_scheduler_main.boto3")
    def test_sem_instance_name_levanta_key_error(self, mock_boto3):
        """Se LIGHTSAIL_INSTANCE_NAME não estiver definida, deve lançar KeyError."""
        # Cria uma cópia do ambiente sem a variável LIGHTSAIL_INSTANCE_NAME.
        # clear=True substitui COMPLETAMENTE os.environ pelo dict fornecido
        # (sem ele, as variáveis originais continuariam presentes mesmo sem a chave removida).
        env_sem_nome = {k: v for k, v in os.environ.items() if k != "LIGHTSAIL_INSTANCE_NAME"}
        with patch.dict(os.environ, env_sem_nome, clear=True):
            with self.assertRaises(KeyError):
                main.lambda_handler({"action": "stop"}, None)


if __name__ == "__main__":
    unittest.main()
