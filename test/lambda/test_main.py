import unittest
from unittest.mock import patch

from app.lambda_api import main


class TestMain(unittest.TestCase):

    @patch("app.lambda_api.main.chamar_glue_etl")
    @patch("app.lambda_api.main.salvar_json_no_s3")
    @patch("app.lambda_api.main.buscar_filmes_por_periodo")
    @patch("app.lambda_api.main.gerar_periodos_mensais")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    @patch("os.getenv")
    def test_lambda_handler(
        self,
        mock_getenv,
        mock_api_key,
        mock_periodos,
        mock_busca,
        mock_s3,
        mock_glue
    ):
        # Mock env vars
        mock_getenv.side_effect = lambda key: {
            "TMDB_SECRET_ARN": "arn",
            "S3_BUCKET_SOR": "bucket",
            "GLUE_ETL_JOB_NAME": "job"
        }[key]

        # Mock funções
        mock_api_key.return_value = "fake_key"
        mock_periodos.return_value = [
            {"data_inicio": "2024-01-01", "data_fim": "2024-01-31"}
        ]
        mock_busca.return_value = [{"id": 1}]
        mock_glue.return_value = {"job_name": "job", "job_run_id": "123"}

        result = main.lambda_handler({}, None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["meses_processados"], 1)
        self.assertEqual(len(result["body"]["arquivos"]), 1)


if __name__ == "__main__":
    unittest.main()