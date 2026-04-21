"""Testes do modulo principal da lambda API."""

import unittest
from unittest.mock import patch

from app.lambda_api.main import lambda_handler


class TestMain(unittest.TestCase):
    @patch("app.lambda_api.main.carregar_filmes_tmdb_por_periodo_mensal")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    def test_lambda_handler_sucesso(self, mock_obter_tmdb_api_key, mock_carregar):
        mock_obter_tmdb_api_key.return_value = "abc123"
        mock_carregar.return_value = {
            "total_meses_processados": 2,
            "limite_paginas_por_consulta": 500,
            "objetos_salvos": [
                "tmdb/discover_movie/year=2000/month=01/movies_2000_01.json",
                "tmdb/discover_movie/year=2000/month=02/movies_2000_02.json",
            ],
        }

        with patch.dict(
            "os.environ",
            {"TMDB_SECRET_ARN": "arn:aws:secretsmanager:tmdb", "S3_BUCKET_SOR": "bucket-sor"},
            clear=True,
        ):
            response = lambda_handler(event={}, context=None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["total_meses_processados"], 2)
        mock_obter_tmdb_api_key.assert_called_once_with("arn:aws:secretsmanager:tmdb")
        mock_carregar.assert_called_once_with(
            api_key="abc123",
            bucket_name="bucket-sor",
            data_inicio="2000-01-01",
            limite_paginas=500,
        )

    def test_lambda_handler_falha_sem_secret_arn(self):
        with patch.dict("os.environ", {"S3_BUCKET_SOR": "bucket-sor"}, clear=True):
            response = lambda_handler(event={}, context=None)

        self.assertEqual(response["statusCode"], 500)
        self.assertIn("TMDB_SECRET_ARN", response["body"])

    def test_lambda_handler_falha_sem_bucket(self):
        with patch.dict("os.environ", {"TMDB_SECRET_ARN": "arn:aws:secretsmanager:tmdb"}, clear=True):
            response = lambda_handler(event={}, context=None)

        self.assertEqual(response["statusCode"], 500)
        self.assertIn("S3_BUCKET_SOR", response["body"])

    @patch("app.lambda_api.main.carregar_filmes_tmdb_por_periodo_mensal")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    def test_lambda_handler_retorna_erro_interno(self, mock_obter_tmdb_api_key, mock_carregar):
        mock_obter_tmdb_api_key.return_value = "abc123"
        mock_carregar.side_effect = RuntimeError("falha ao processar")

        with patch.dict(
            "os.environ",
            {"TMDB_SECRET_ARN": "arn:aws:secretsmanager:tmdb", "S3_BUCKET_SOR": "bucket-sor"},
            clear=True,
        ):
            response = lambda_handler(event={}, context=None)

        self.assertEqual(response["statusCode"], 500)
        self.assertIn("falha ao processar", response["body"])


if __name__ == "__main__":
    unittest.main()
