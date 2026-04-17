"""Testes do modulo principal da aplicacao."""

import unittest
from unittest.mock import patch

from app.lambda_api.main import lambda_handler, processar_numero

class TestMain(unittest.TestCase):
    """Valida as mensagens retornadas pela funcao processar_numero."""

    def test_processar_numero_par(self):
        # Testa a lógica para um número par
        esperado = "O número 10 é par."
        resultado = processar_numero(10)
        self.assertEqual(resultado, esperado)

    def test_processar_numero_impar(self):
        # Testa a lógica para um número ímpar
        esperado = "O número 7 é ímpar."
        resultado = processar_numero(7)
        self.assertEqual(resultado, esperado)

    @patch("app.lambda_api.main.chamar_glue_etl_e_data_quality")
    def test_lambda_handler_dispara_glue_no_final(self, mock_chamar_glue):
        mock_chamar_glue.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-111",
            "etl_job_name": "etl-job",
            "etl_job_run_id": "jr-222",
        }

        event = {
            "numero": 8,
            "glue_etl_job_name": "etl-job",
            "glue_data_quality_job_name": "dq-job",
        }
        response = lambda_handler(event, context=None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["mensagem"], "O número 8 é par.")
        self.assertEqual(response["body"]["glue_execucao"]["etl_job_run_id"], "jr-222")
        mock_chamar_glue.assert_called_once_with(
            etl_job_name="etl-job",
            data_quality_job_name="dq-job",
        )

    @patch("app.lambda_api.main.chamar_glue_etl_e_data_quality")
    def test_lambda_handler_usa_valores_padrao_do_evento(self, mock_chamar_glue):
        mock_chamar_glue.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-333",
            "etl_job_name": "etl-job",
            "etl_job_run_id": "jr-444",
        }

        response = lambda_handler(event={}, context=None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["numero"], 10)
        mock_chamar_glue.assert_called_once_with(
            etl_job_name=None,
            data_quality_job_name=None,
        )

if __name__ == '__main__':
    unittest.main()
    