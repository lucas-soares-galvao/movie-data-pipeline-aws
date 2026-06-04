"""
test_main.py — Testes unitários do lambda_handler.

Simula search_catalog e recommend para testar apenas o fluxo do handler.
"""

import json
import unittest
from unittest.mock import patch

ENV_VARS = {
    "ATHENA_DATABASE": "db_tmdb",
    "S3_BUCKET_TEMP": "meu-bucket-temp",
    "OPENAI_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123:secret:openai",
}

FILMES_MOCK = [
    {
        "title": "Interstellar",
        "original_title": "Interstellar",
        "year": "2014",
        "media_type": "movie",
        "genre_names": "Science Fiction, Drama",
        "vote_average": "8.6",
        "language_name": "English",
        "overview": "Uma equipe explora o espaço.",
        "recommendation_reason": "Combina com ficção científica filosófica.",
    }
]

EVENTO_POST = {
    "requestContext": {"http": {"method": "POST"}},
    "body": json.dumps({"preferences": "ficção científica filosófica"}),
}


class TestLambdaHandler(unittest.TestCase):

    @patch.dict("os.environ", ENV_VARS)
    @patch("main.recommend", return_value=FILMES_MOCK)
    @patch("main.search_catalog", return_value=FILMES_MOCK)
    def test_retorna_200_com_filmes(self, mock_search, mock_recommend):
        from main import lambda_handler
        resposta = lambda_handler(EVENTO_POST, {})

        self.assertEqual(resposta["statusCode"], 200)
        body = json.loads(resposta["body"])
        self.assertEqual(len(body["movies"]), 1)
        self.assertEqual(body["movies"][0]["title"], "Interstellar")

    @patch.dict("os.environ", ENV_VARS)
    @patch("main.search_catalog")
    def test_retorna_400_quando_preferencia_muito_curta(self, mock_search):
        from main import lambda_handler
        evento = {**EVENTO_POST, "body": json.dumps({"preferences": "curto"})}
        resposta = lambda_handler(evento, {})

        self.assertEqual(resposta["statusCode"], 400)
        mock_search.assert_not_called()

    @patch.dict("os.environ", ENV_VARS)
    @patch("main.search_catalog")
    def test_retorna_400_quando_preferencia_muito_longa(self, mock_search):
        from main import lambda_handler
        evento = {**EVENTO_POST, "body": json.dumps({"preferences": "x" * 501})}
        resposta = lambda_handler(evento, {})

        self.assertEqual(resposta["statusCode"], 400)
        mock_search.assert_not_called()

    @patch.dict("os.environ", ENV_VARS)
    @patch("main.recommend")
    @patch("main.search_catalog", return_value=[])
    def test_retorna_404_quando_sem_filmes(self, mock_search, mock_recommend):
        from main import lambda_handler
        resposta = lambda_handler(EVENTO_POST, {})

        self.assertEqual(resposta["statusCode"], 404)
        mock_recommend.assert_not_called()

    @patch.dict("os.environ", ENV_VARS)
    @patch("main.search_catalog")
    def test_cors_presente_na_resposta(self, mock_search):
        from main import lambda_handler
        evento = {"requestContext": {"http": {"method": "OPTIONS"}}, "body": None}
        resposta = lambda_handler(evento, {})

        self.assertIn("Access-Control-Allow-Origin", resposta["headers"])
        self.assertEqual(resposta["headers"]["Access-Control-Allow-Origin"], "*")


if __name__ == "__main__":
    unittest.main()
