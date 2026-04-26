import unittest
from unittest.mock import patch

from app.lambda_api import main


class TestMain(unittest.TestCase):



    @patch("app.lambda_api.main.chamar_glue_etl")
    @patch("app.lambda_api.main.processar_generos")
    @patch("app.lambda_api.main.processar_discover")
    @patch("app.lambda_api.main.gerar_periodos_mensais")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    @patch("os.getenv")
    def test_lambda_handler_movies(self, mock_getenv, mock_api_key, mock_periodos, mock_processar_discover, mock_processar_generos, mock_glue):
        mock_getenv.side_effect = lambda key: {
            "TMDB_SECRET_ARN": "arn",
            "S3_BUCKET_SOR": "bucket",
            "GLUE_ETL_JOB_NAME": "job"
        }[key]
        mock_api_key.return_value = "fake_key"
        mock_periodos.return_value = [
            {"data_inicio": "2024-01-01", "data_fim": "2024-01-31"}
        ]
        mock_processar_discover.return_value = ["filme1.json"]
        mock_processar_generos.return_value = ["generos_filme.json"]
        mock_glue.return_value = {"job_name": "job", "job_run_id": "123"}

        result = main.lambda_handler({"tipo": "movie"}, None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["tipo"], "movie")
        self.assertEqual(result["body"]["arquivos_discover"], ["filme1.json"])
        self.assertEqual(result["body"]["arquivos_generos"], ["generos_filme.json"])
        self.assertEqual(result["body"]["glue"], {"job_name": "job", "job_run_id": "123"})

    @patch("app.lambda_api.main.chamar_glue_etl")
    @patch("app.lambda_api.main.processar_generos")
    @patch("app.lambda_api.main.processar_discover")
    @patch("app.lambda_api.main.gerar_periodos_mensais")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    @patch("os.getenv")
    def test_lambda_handler_tv(self, mock_getenv, mock_api_key, mock_periodos, mock_processar_discover, mock_processar_generos, mock_glue):
        mock_getenv.side_effect = lambda key: {
            "TMDB_SECRET_ARN": "arn",
            "S3_BUCKET_SOR": "bucket",
            "GLUE_ETL_JOB_NAME": "job"
        }[key]
        mock_api_key.return_value = "fake_key"
        mock_periodos.return_value = [
            {"data_inicio": "2024-01-01", "data_fim": "2024-01-31"}
        ]
        mock_processar_discover.return_value = ["tv1.json"]
        mock_processar_generos.return_value = ["generos_tv.json"]
        mock_glue.return_value = {"job_name": "job", "job_run_id": "123"}

        result = main.lambda_handler({"tipo": "tv"}, None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["tipo"], "tv")
        self.assertEqual(result["body"]["arquivos_discover"], ["tv1.json"])
        self.assertEqual(result["body"]["arquivos_generos"], ["generos_tv.json"])
        self.assertEqual(result["body"]["glue"], {"job_name": "job", "job_run_id": "123"})


if __name__ == "__main__":
    unittest.main()