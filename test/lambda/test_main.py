"""Testes do modulo principal da aplicacao."""

import unittest
from unittest.mock import patch

from app.lambda_api.main import lambda_handler


class TestMain(unittest.TestCase):
    @patch("app.lambda_api.main.chamar_glue_etl_e_data_quality")
    @patch("app.lambda_api.main.carregar_tmdb_por_ano_e_salvar_sor")
    @patch("app.lambda_api.main.buscar_filme_tmdb")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    def test_lambda_handler_dispara_glue_tmdb_e_ingestao_sor(
        self,
        mock_obter_key,
        mock_buscar_tmdb,
        mock_ingestao_sor,
        mock_chamar_glue,
    ):
        mock_obter_key.return_value = "abc123"
        mock_buscar_tmdb.return_value = {"results": [{"title": "Matrix"}]}
        mock_ingestao_sor.return_value = {
            "bucket": "bucket-sor",
            "filmes_encontrados": 100,
            "objetos_s3_gravados": 12,
        }
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
        self.assertEqual(response["body"]["sor_ingestao"]["objetos_s3_gravados"], 12)
        self.assertIsNone(response["body"]["sor_error"])
        mock_ingestao_sor.assert_called_once()
        self.assertNotIn("mensagem", response["body"])
        self.assertNotIn("numero", response["body"])

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

    @patch("app.lambda_api.main.chamar_glue_etl_e_data_quality")
    @patch("app.lambda_api.main.carregar_tmdb_por_ano_e_salvar_sor")
    @patch("app.lambda_api.main.obter_tmdb_api_key")
    def test_lambda_handler_ignora_ingestao_sor_quando_desativado(
        self,
        mock_obter_key,
        mock_ingestao_sor,
        mock_chamar_glue,
    ):
        mock_obter_key.return_value = "abc123"
        mock_chamar_glue.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-111",
            "etl_job_name": "etl-job",
            "etl_job_run_id": "jr-222",
        }

        response = lambda_handler(event={"executar_ingestao_sor": False}, context=None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIsNone(response["body"]["sor_ingestao"])
        self.assertIsNone(response["body"]["sor_error"])
        mock_ingestao_sor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
    