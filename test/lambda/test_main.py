"""Testes do modulo principal da aplicacao."""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

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

    @patch("app.lambda_api.main.chamar_glue_etl_e_data_quality")
    @patch("app.lambda_api.main.upload_arquivo_para_s3")
    def test_lambda_handler_faz_upload_do_arquivo(self, mock_upload, mock_chamar_glue):
        """Testa se a lambda faz upload do arquivo teste.txt para S3."""
        mock_chamar_glue.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-111",
            "etl_job_name": "etl-job",
            "etl_job_run_id": "jr-222",
        }
        mock_upload.return_value = {
            "bucket": "lsg-sa-east-1-bucket-sor",
            "key": "teste.txt",
            "status": "uploaded",
        }

        env = {"S3_BUCKET_SOR": "lsg-sa-east-1-bucket-sor"}
        with patch.dict(os.environ, env):
            response = lambda_handler(
                event={
                    "numero": 5,
                    "glue_etl_job_name": "etl-job",
                    "glue_data_quality_job_name": "dq-job",
                },
                context=None,
            )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["s3_upload"]["status"], "uploaded")
        mock_upload.assert_called_once()

    @patch("app.lambda_api.main.chamar_glue_etl_e_data_quality")
    def test_lambda_handler_sem_s3_bucket_sor(self, mock_chamar_glue):
        """Testa lambda quando S3_BUCKET_SOR nao esta configurado."""
        mock_chamar_glue.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-111",
            "etl_job_name": "etl-job",
            "etl_job_run_id": "jr-222",
        }

        with patch.dict(os.environ, {}, clear=True):
            response = lambda_handler(
                event={
                    "numero": 3,
                    "glue_etl_job_name": "etl-job",
                    "glue_data_quality_job_name": "dq-job",
                },
                context=None,
            )

        self.assertEqual(response["statusCode"], 200)
        self.assertIsNone(response["body"]["s3_upload"])

if __name__ == '__main__':
    unittest.main()
    