"""
test_athena.py — Testes unitários de src/athena.py.

Simula as chamadas ao boto3 sem fazer requisições reais à AWS.
"""

import unittest
from unittest.mock import MagicMock, patch


# Variáveis de ambiente necessárias antes do import do módulo
ENV_VARS = {
    "ATHENA_DATABASE": "db_tmdb",
    "S3_BUCKET_TEMP": "meu-bucket-temp",
    "OPENAI_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:openai",
}


def _make_athena_client(state="SUCCEEDED", rows=None):
    """Cria um mock do cliente Athena com respostas configuráveis."""
    client = MagicMock()
    client.start_query_execution.return_value = {"QueryExecutionId": "exec-123"}
    client.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": state}}
    }
    if rows is None:
        rows = [
            # Linha de cabeçalho
            {"Data": [{"VarCharValue": col} for col in ["title", "year", "vote_average", "genre_names", "overview", "media_type", "language_name", "origin_country_name", "id", "original_title"]]},
            # Linha de dados
            {"Data": [{"VarCharValue": v} for v in ["Inception", "2010", "8.8", "Science Fiction", "Um sonho dentro de um sonho.", "movie", "English", "United States", "27205", "Inception"]]},
        ]
    client.get_query_results.return_value = {"ResultSet": {"Rows": rows}}
    return client


class TestSearchCatalog(unittest.TestCase):

    @patch.dict("os.environ", ENV_VARS)
    @patch("src.athena.boto3")
    def test_retorna_lista_de_filmes(self, mock_boto3):
        mock_boto3.client.return_value = _make_athena_client()

        from src.athena import search_catalog
        resultado = search_catalog(genres=["Science Fiction"])

        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["title"], "Inception")
        self.assertEqual(resultado[0]["vote_average"], "8.8")

    @patch.dict("os.environ", ENV_VARS)
    @patch("src.athena.boto3")
    def test_filtro_genero_presente_no_sql(self, mock_boto3):
        mock_client = _make_athena_client()
        mock_boto3.client.return_value = mock_client

        from src.athena import search_catalog
        search_catalog(genres=["Horror"])

        sql_executado = mock_client.start_query_execution.call_args[1]["QueryString"]
        self.assertIn("horror", sql_executado.lower())

    @patch.dict("os.environ", ENV_VARS)
    @patch("src.athena.boto3")
    def test_filtro_ano_presente_no_sql(self, mock_boto3):
        mock_client = _make_athena_client()
        mock_boto3.client.return_value = mock_client

        from src.athena import search_catalog
        search_catalog(year_min=1990, year_max=1999)

        sql = mock_client.start_query_execution.call_args[1]["QueryString"]
        self.assertIn("1990", sql)
        self.assertIn("1999", sql)

    @patch.dict("os.environ", ENV_VARS)
    @patch("src.athena.boto3")
    def test_retorna_lista_vazia_sem_rows(self, mock_boto3):
        # Apenas a linha de cabeçalho, sem dados
        rows = [{"Data": [{"VarCharValue": "title"}]}]
        mock_boto3.client.return_value = _make_athena_client(rows=rows)

        from src.athena import search_catalog
        resultado = search_catalog()

        self.assertEqual(resultado, [])

    @patch.dict("os.environ", ENV_VARS)
    @patch("src.athena.time")
    @patch("src.athena.boto3")
    def test_timeout_levanta_excecao(self, mock_boto3, mock_time):
        mock_time.sleep = MagicMock()
        client = MagicMock()
        client.start_query_execution.return_value = {"QueryExecutionId": "exec-timeout"}
        client.get_query_execution.return_value = {
            "QueryExecution": {"Status": {"State": "RUNNING"}}
        }
        mock_boto3.client.return_value = client

        from src.athena import search_catalog, POLL_TIMEOUT, POLL_INTERVAL

        # Simula que POLL_TIMEOUT chamadas de sleep já foram feitas
        call_count = POLL_TIMEOUT // POLL_INTERVAL + 1
        mock_time.sleep.side_effect = [None] * call_count

        with self.assertRaises(TimeoutError):
            search_catalog()

    @patch.dict("os.environ", ENV_VARS)
    @patch("src.athena.boto3")
    def test_query_falhou_levanta_runtime_error(self, mock_boto3):
        mock_boto3.client.return_value = _make_athena_client(state="FAILED")

        from src.athena import search_catalog
        with self.assertRaises(RuntimeError):
            search_catalog()


if __name__ == "__main__":
    unittest.main()
