"""Testes do modulo principal da aplicacao."""

import unittest
from unittest.mock import patch

from app.lambda_api.main import lambda_handler


class TestMain(unittest.TestCase):
    @patch("app.lambda_api.main.chamar_glue_etl_e_data_quality")
    @patch("app.lambda_api.main.buscar_filme_tmdb")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    def test_lambda_handler_dispara_glue_e_tmdb(self, mock_obter_key, mock_buscar_tmdb, mock_chamar_glue):
        mock_obter_key.return_value = "abc123"
        mock_buscar_tmdb.return_value = {"results": [{"title": "Matrix"}]}
        mock_chamar_glue.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-111",
            "etl_job_name": "etl-job",
            "etl_job_run_id": "jr-222",
        }

        response = lambda_handler(
            {
                "query": "matrix",
                "glue_etl_job_name": "etl-job",
                "glue_data_quality_job_name": "dq-job",
            },
            context=None,
        )

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["tmdb_query"], "matrix")
        self.assertEqual(response["body"]["tmdb_result"]["results"][0]["title"], "Matrix")
        self.assertIsNone(response["body"]["tmdb_error"])
        self.assertNotIn("mensagem", response["body"])
        self.assertNotIn("numero", response["body"])
        self.assertNotIn("s3_upload", response["body"])

    @patch("app.lambda_api.main.chamar_glue_etl_e_data_quality")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    def test_lambda_handler_retorna_tmdb_error_quando_falha(self, mock_obter_key, mock_chamar_glue):
        mock_obter_key.side_effect = ValueError("segredo nao encontrado")
        mock_chamar_glue.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-111",
            "etl_job_name": "etl-job",
            "etl_job_run_id": "jr-222",
        }

        response = lambda_handler(event={"query": "matrix"}, context=None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIsNone(response["body"]["tmdb_result"])
        self.assertEqual(response["body"]["tmdb_error"], "segredo nao encontrado")


if __name__ == "__main__":
    unittest.main()
    