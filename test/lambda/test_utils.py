"""Testes unitarios das funcoes utilitarias da lambda API."""

import unittest
from unittest.mock import MagicMock, patch

from app.lambda_api.src.utils import (
    buscar_filme_por_periodo_de_lancamento,
    carregar_filmes_tmdb_por_periodo_mensal,
    gerar_intervalos_mensais,
    obter_tmdb_api_key,
    salvar_json_no_s3,
)


class TestObterTmdbApiKey(unittest.TestCase):
    @patch("app.lambda_api.src.utils.boto3.client")
    def test_obter_tmdb_api_key_com_sucesso(self, mock_boto_client):
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": '{"TMDB_API_KEY":"abc123"}'}
        mock_boto_client.return_value = mock_client

        result = obter_tmdb_api_key("arn:aws:secretsmanager:tmdb")

        self.assertEqual(result, {"tipo": "api_key", "valor": "abc123"})
        mock_client.get_secret_value.assert_called_once_with(SecretId="arn:aws:secretsmanager:tmdb")

    @patch("app.lambda_api.src.utils.boto3.client")
    def test_obter_tmdb_api_key_com_read_access_token(self, mock_boto_client):
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"TMDB_READ_ACCESS_TOKEN":"token.tmdb.v4"}'
        }
        mock_boto_client.return_value = mock_client

        result = obter_tmdb_api_key("arn:aws:secretsmanager:tmdb")

        self.assertEqual(result, {"tipo": "bearer", "valor": "token.tmdb.v4"})

    @patch("app.lambda_api.src.utils.boto3.client")
    def test_obter_tmdb_api_key_com_chave_minuscula(self, mock_boto_client):
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"tmdb_api_key":"abc123"}'
        }
        mock_boto_client.return_value = mock_client

        result = obter_tmdb_api_key("arn:aws:secretsmanager:tmdb")

        self.assertEqual(result, {"tipo": "api_key", "valor": "abc123"})

    @patch("app.lambda_api.src.utils.boto3.client")
    def test_obter_tmdb_api_key_com_token_no_campo_tmdb_api_key(self, mock_boto_client):
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"tmdb_api_key":"token.parte1.parte2"}'
        }
        mock_boto_client.return_value = mock_client

        result = obter_tmdb_api_key("arn:aws:secretsmanager:tmdb")

        self.assertEqual(result, {"tipo": "bearer", "valor": "token.parte1.parte2"})

    @patch("app.lambda_api.src.utils.boto3.client")
    def test_obter_tmdb_api_key_lanca_runtime_error(self, mock_boto_client):
        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = Exception("secret not found")
        mock_boto_client.return_value = mock_client

        with self.assertRaises(RuntimeError):
            obter_tmdb_api_key("arn:aws:secretsmanager:tmdb")


class TestGerarIntervalosMensais(unittest.TestCase):
    def test_gerar_intervalos_mensais_periodo_fixo(self):
        intervalos = gerar_intervalos_mensais("2026-01-15", "2026-03-10")

        self.assertEqual(
            intervalos,
            [
                {"primeiro_dia": "2026-01-01", "ultimo_dia": "2026-01-31"},
                {"primeiro_dia": "2026-02-01", "ultimo_dia": "2026-02-28"},
                {"primeiro_dia": "2026-03-01", "ultimo_dia": "2026-03-10"},
            ],
        )

    def test_gerar_intervalos_mensais_lanca_erro_quando_inicio_maior_que_fim(self):
        with self.assertRaises(ValueError):
            gerar_intervalos_mensais("2026-03-11", "2026-03-10")


class TestBuscarFilmePorPeriodoDeLancamento(unittest.TestCase):
    @patch("app.lambda_api.src.utils.requests.get")
    def test_buscar_filme_com_paginacao_e_limite(self, mock_get):
        periodo = {"primeiro_dia": "2026-01-01", "ultimo_dia": "2026-01-31"}

        resp1 = MagicMock()
        resp1.json.return_value = {
            "total_pages": 3,
            "results": [{"id": 1}, {"id": 2}],
        }
        resp2 = MagicMock()
        resp2.json.return_value = {
            "total_pages": 3,
            "results": [{"id": 3}],
        }

        mock_get.side_effect = [resp1, resp2]

        payload = buscar_filme_por_periodo_de_lancamento(
            api_key="abc123",
            periodo=periodo,
            limite_paginas=2,
        )

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(payload["paginas_processadas"], 2)
        self.assertEqual(payload["limite_paginas"], 2)
        self.assertEqual(payload["total_paginas_disponiveis"], 3)
        self.assertEqual(payload["total_filmes"], 3)
        self.assertEqual(len(payload["results"]), 3)

        primeiro_params = mock_get.call_args_list[0].kwargs["params"]
        segundo_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertEqual(primeiro_params["page"], 1)
        self.assertEqual(segundo_params["page"], 2)
        self.assertEqual(primeiro_params["api_key"], "abc123")

    @patch("app.lambda_api.src.utils.requests.get")
    def test_buscar_filme_com_bearer_token(self, mock_get):
        periodo = {"primeiro_dia": "2026-01-01", "ultimo_dia": "2026-01-31"}

        resp = MagicMock()
        resp.json.return_value = {"total_pages": 1, "results": [{"id": 1}]}
        mock_get.return_value = resp

        payload = buscar_filme_por_periodo_de_lancamento(
            api_key={"tipo": "bearer", "valor": "token.tmdb.v4"},
            periodo=periodo,
            limite_paginas=1,
        )

        self.assertEqual(payload["total_filmes"], 1)
        request_kwargs = mock_get.call_args.kwargs
        self.assertNotIn("api_key", request_kwargs["params"])
        self.assertEqual(request_kwargs["headers"]["Authorization"], "Bearer token.tmdb.v4")

    @patch("app.lambda_api.src.utils.requests.get")
    def test_buscar_filme_lanca_runtime_error(self, mock_get):
        mock_get.side_effect = Exception("erro de rede")

        with self.assertRaises(RuntimeError):
            buscar_filme_por_periodo_de_lancamento(
                api_key="abc123",
                periodo={"primeiro_dia": "2026-01-01", "ultimo_dia": "2026-01-31"},
                limite_paginas=1,
            )


class TestSalvarJsonNoS3(unittest.TestCase):
    @patch("app.lambda_api.src.utils.boto3.client")
    def test_salvar_json_no_s3(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        salvar_json_no_s3(
            bucket_name="bucket-sor",
            object_key="tmdb/discover_movie/year=2026/month=01/movies_2026_01.json",
            payload={"ok": True},
        )

        mock_s3.put_object.assert_called_once()
        kwargs = mock_s3.put_object.call_args.kwargs
        self.assertEqual(kwargs["Bucket"], "bucket-sor")
        self.assertIn("year=2026/month=01", kwargs["Key"])


class TestCarregarFilmesTmdbPorPeriodoMensal(unittest.TestCase):
    @patch("app.lambda_api.src.utils.salvar_json_no_s3")
    @patch("app.lambda_api.src.utils.buscar_filme_por_periodo_de_lancamento")
    @patch("app.lambda_api.src.utils.gerar_intervalos_mensais")
    def test_carregar_filmes_por_periodo_mensal(
        self,
        mock_gerar_intervalos,
        mock_buscar,
        mock_salvar,
    ):
        mock_gerar_intervalos.return_value = [
            {"primeiro_dia": "2026-01-01", "ultimo_dia": "2026-01-31"},
            {"primeiro_dia": "2026-02-01", "ultimo_dia": "2026-02-28"},
        ]
        mock_buscar.side_effect = [
            {"results": [{"id": 1}]},
            {"results": [{"id": 2}]},
        ]

        resumo = carregar_filmes_tmdb_por_periodo_mensal(
            api_key="abc123",
            bucket_name="bucket-sor",
            data_inicio="2000-01-01",
            limite_paginas=500,
        )

        self.assertEqual(resumo["total_meses_processados"], 2)
        self.assertEqual(resumo["limite_paginas_por_consulta"], 500)
        self.assertEqual(len(resumo["objetos_salvos"]), 2)
        self.assertIn("year=2026/month=01", resumo["objetos_salvos"][0])
        self.assertIn("year=2026/month=02", resumo["objetos_salvos"][1])

        mock_buscar.assert_any_call(
            api_key="abc123",
            periodo={"primeiro_dia": "2026-01-01", "ultimo_dia": "2026-01-31"},
            limite_paginas=500,
        )
        self.assertEqual(mock_salvar.call_count, 2)


if __name__ == "__main__":
    unittest.main()
