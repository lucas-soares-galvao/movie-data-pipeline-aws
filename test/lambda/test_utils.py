"""Testes unitarios das funcoes utilitarias."""

import os
import tempfile
import urllib.error
import unittest
from unittest.mock import patch, MagicMock

from app.lambda_api.src.utils import (
    buscar_filme_tmdb,
    buscar_filmes_tmdb_por_ano,
    buscar_filmes_tmdb_por_ano_mes,
    carregar_tmdb_por_ano_e_salvar_sor,
    chamar_glue_etl_e_data_quality,
    obter_secret,
    obter_tmdb_api_key,
    salvar_json_em_s3,
)

class _FakeGlueClient:
    def __init__(self):
        self.calls = []

    def start_job_run(self, JobName):
        self.calls.append(JobName)
        return {"JobRunId": f"run-{JobName}"}


class _FakeGlueClientConcurrent:
    class exceptions:
        class ConcurrentRunsExceededException(Exception):
            pass

    def __init__(self):
        self.calls = []

    def start_job_run(self, JobName):
        self.calls.append(JobName)
        raise self.exceptions.ConcurrentRunsExceededException()


class TestChamarGlueEtlEDataQuality(unittest.TestCase):
    def test_dispara_data_quality_e_etl_com_nomes_explicitos(self):
        fake_client = _FakeGlueClient()

        result = chamar_glue_etl_e_data_quality(
            etl_job_name="etl-job",
            data_quality_job_name="dq-job",
            glue_client=fake_client,
        )

        self.assertEqual(fake_client.calls, ["dq-job", "etl-job"])
        self.assertEqual(result["data_quality_job_run_id"], "run-dq-job")
        self.assertEqual(result["etl_job_run_id"], "run-etl-job")

    def test_falha_quando_nome_etl_nao_informado(self):
        fake_client = _FakeGlueClient()

        with self.assertRaises(ValueError):
            chamar_glue_etl_e_data_quality(
                etl_job_name=None,
                data_quality_job_name="dq-job",
                glue_client=fake_client,
            )

    def test_falha_quando_nome_data_quality_nao_informado(self):
        fake_client = _FakeGlueClient()

        with self.assertRaises(ValueError):
            chamar_glue_etl_e_data_quality(
                etl_job_name="etl-job",
                data_quality_job_name=None,
                glue_client=fake_client,
            )

    def test_usa_nomes_dos_jobs_vindos_do_ambiente(self):
        fake_client = _FakeGlueClient()
        env = {
            "GLUE_ETL_JOB_NAME": "etl-job-env",
            "GLUE_DATA_QUALITY_JOB_NAME": "dq-job-env",
        }

        with patch.dict(os.environ, env, clear=True):
            result = chamar_glue_etl_e_data_quality(
                etl_job_name=None,
                data_quality_job_name=None,
                glue_client=fake_client,
            )

        self.assertEqual(fake_client.calls, ["dq-job-env", "etl-job-env"])
        self.assertEqual(result["data_quality_job_name"], "dq-job-env")
        self.assertEqual(result["etl_job_name"], "etl-job-env")

    def test_retorna_status_already_running_quando_excede_concorrencia(self):
        fake_client = _FakeGlueClientConcurrent()

        result = chamar_glue_etl_e_data_quality(
            etl_job_name="etl-job",
            data_quality_job_name="dq-job",
            glue_client=fake_client,
        )

        self.assertEqual(fake_client.calls, ["dq-job", "etl-job"])
        self.assertIsNone(result["data_quality_job_run_id"])
        self.assertIsNone(result["etl_job_run_id"])
        self.assertEqual(result["data_quality_job_status"], "already_running")
        self.assertEqual(result["etl_job_status"], "already_running")


class _FakeSecretsManagerClient:
    def __init__(self, secret_string):
        self.secret_string = secret_string

    def get_secret_value(self, SecretId):
        return {"SecretString": self.secret_string}


class _FakeUrlOpenResponse:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self):
        return self._body


class TestTMDBIntegrationUtils(unittest.TestCase):
    def test_obter_secret_com_json(self):
        client = _FakeSecretsManagerClient('{"api_key":"abc123"}')
        result = obter_secret(secret_id="arn:aws:secretsmanager:::secret:tmdb", secrets_client=client)
        self.assertEqual(result["api_key"], "abc123")

    def test_obter_secret_com_string_pura(self):
        client = _FakeSecretsManagerClient("abc123")
        result = obter_secret(secret_id="arn:aws:secretsmanager:::secret:tmdb", secrets_client=client)
        self.assertEqual(result["api_key"], "abc123")

    def test_obter_tmdb_api_key(self):
        client = _FakeSecretsManagerClient('{"tmdb_api_key":"abc123"}')
        result = obter_tmdb_api_key(secret_id="arn:aws:secretsmanager:::secret:tmdb", secrets_client=client)
        self.assertEqual(result, "abc123")

    def test_obter_tmdb_api_key_fallback_api_key(self):
        client = _FakeSecretsManagerClient('{"api_key":"abc123"}')
        result = obter_tmdb_api_key(secret_id="arn:aws:secretsmanager:::secret:tmdb", secrets_client=client)
        self.assertEqual(result, "abc123")

    def test_obter_tmdb_api_key_com_access_token(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature"
        client = _FakeSecretsManagerClient('{"tmdb_api_key":"' + token + '"}')
        result = obter_tmdb_api_key(secret_id="arn:aws:secretsmanager:::secret:tmdb", secrets_client=client)
        self.assertEqual(result, token)

    def test_buscar_filme_tmdb(self):
        payload = b'{"results":[{"title":"Matrix"}]}'

        def fake_urlopen(url, timeout):
            self.assertIn("api_key=abc123", url)
            self.assertIn("query=matrix", url)
            self.assertEqual(timeout, 10)
            return _FakeUrlOpenResponse(payload)

        result = buscar_filme_tmdb(query="matrix", api_key="abc123", urlopen_func=fake_urlopen)
        self.assertEqual(result["results"][0]["title"], "Matrix")

    def test_buscar_filme_tmdb_com_bearer_token(self):
        payload = b'{"results":[{"title":"Matrix"}]}'

        def fake_urlopen(request, timeout):
            self.assertEqual(timeout, 10)
            self.assertIn("query=matrix", request.full_url)
            self.assertNotIn("api_key=", request.full_url)
            self.assertEqual(request.headers["Authorization"], "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature")
            return _FakeUrlOpenResponse(payload)

        result = buscar_filme_tmdb(
            query="matrix",
            api_key="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature",
            urlopen_func=fake_urlopen,
        )
        self.assertEqual(result["results"][0]["title"], "Matrix")

    def test_buscar_filmes_tmdb_por_ano(self):
        payload = b'{"results":[{"title":"Matrix"}]}'

        def fake_urlopen(url, timeout):
            self.assertIn("primary_release_year=2003", url)
            self.assertIn("page=1", url)
            self.assertIn("api_key=abc123", url)
            self.assertEqual(timeout, 10)
            return _FakeUrlOpenResponse(payload)

        result = buscar_filmes_tmdb_por_ano(ano=2003, api_key="abc123", urlopen_func=fake_urlopen)
        self.assertEqual(result["results"][0]["title"], "Matrix")

    def test_buscar_filmes_tmdb_por_ano_mes(self):
        payload = b'{"results":[{"title":"Matrix"}]}'

        def fake_urlopen(url, timeout):
            self.assertIn("primary_release_date.gte=2025-05-01", url)
            self.assertIn("primary_release_date.lte=2025-05-31", url)
            self.assertIn("sort_by=popularity.desc", url)
            self.assertIn("api_key=abc123", url)
            self.assertEqual(timeout, 10)
            return _FakeUrlOpenResponse(payload)

        result = buscar_filmes_tmdb_por_ano_mes(ano=2025, mes=5, api_key="abc123", urlopen_func=fake_urlopen)
        self.assertEqual(result["results"][0]["title"], "Matrix")

    @patch("app.lambda_api.src.utils.time.sleep")
    def test_buscar_filmes_tmdb_por_ano_mes_retry_502(self, _mock_sleep):
        payload = b'{"results":[{"title":"Matrix"}]}'
        attempts = {"count": 0}

        def fake_urlopen(url, timeout):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise urllib.error.HTTPError(url=url, code=502, msg="Bad Gateway", hdrs=None, fp=None)
            return _FakeUrlOpenResponse(payload)

        result = buscar_filmes_tmdb_por_ano_mes(
            ano=2025,
            mes=5,
            api_key="abc123",
            urlopen_func=fake_urlopen,
            max_retries=2,
        )

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(result["results"][0]["title"], "Matrix")


class TestCargaSorParticionada(unittest.TestCase):
    def test_salvar_json_em_s3(self):
        mock_s3_client = MagicMock()

        salvar_json_em_s3(
            bucket_name="bucket-sor",
            s3_key="tmdb/discover_movie/year=2003/month=05/arquivo.json",
            payload={"ok": True},
            s3_client=mock_s3_client,
        )

        mock_s3_client.put_object.assert_called_once()
        kwargs = mock_s3_client.put_object.call_args[1]
        self.assertEqual(kwargs["Bucket"], "bucket-sor")
        self.assertEqual(kwargs["Key"], "tmdb/discover_movie/year=2003/month=05/arquivo.json")

    def test_carregar_tmdb_por_ano_e_salvar_sor_particiona_year_month(self):
        def fake_buscar_por_ano_mes_func(ano, mes, api_key, page, sort_by, timeout, urlopen_func, max_retries):
            if ano == 2000 and mes == 1:
                return {
                    "results": [
                        {"id": 1, "release_date": "2000-01-10", "title": "A"},
                        {"id": 2, "release_date": "2000-01-20", "title": "B"},
                    ]
                }
            if ano == 2001 and mes == 2:
                return {
                    "results": [
                        {"id": 3, "release_date": "2001-02-14", "title": "C"},
                    ]
                }
            return {"results": []}

        mock_s3_client = MagicMock()

        resumo = carregar_tmdb_por_ano_e_salvar_sor(
            api_key="abc123",
            bucket_name="bucket-sor",
            ano_inicio=2000,
            ano_fim=2001,
            paginas_por_ano=1,
            paginas_por_mes=1,
            s3_prefix="tmdb/discover_movie",
            s3_client=mock_s3_client,
            buscar_por_ano_mes_func=fake_buscar_por_ano_mes_func,
        )

        self.assertEqual(resumo["filmes_encontrados"], 3)
        self.assertEqual(resumo["particoes_geradas"], 2)
        self.assertEqual(resumo["objetos_s3_gravados"], 2)

        keys = [call.kwargs["Key"] for call in mock_s3_client.put_object.call_args_list]
        self.assertTrue(any("year=2000/month=01" in key for key in keys))
        self.assertTrue(any("year=2001/month=02" in key for key in keys))

    def test_carregar_tmdb_por_ano_auto_paginas_quando_zero(self):
        chamadas = []

        def fake_buscar_por_ano_mes_func(ano, mes, api_key, page, sort_by, timeout, urlopen_func, max_retries):
            chamadas.append((ano, mes, page))
            if mes != 5:
                return {"total_pages": 1, "results": []}
            if page == 1:
                return {
                    "total_pages": 2,
                    "results": [
                        {"id": 1, "release_date": "2025-01-10", "title": "A"},
                    ],
                }
            return {
                "total_pages": 2,
                "results": [
                    {"id": 2, "release_date": "2025-05-11", "title": "B"},
                ],
            }

        mock_s3_client = MagicMock()

        resumo = carregar_tmdb_por_ano_e_salvar_sor(
            api_key="abc123",
            bucket_name="bucket-sor",
            ano_inicio=2025,
            ano_fim=2025,
            paginas_por_ano=0,
            paginas_por_mes=0,
            s3_prefix="tmdb/discover_movie",
            s3_client=mock_s3_client,
            buscar_por_ano_mes_func=fake_buscar_por_ano_mes_func,
        )

        self.assertIn((2025, 5, 1), chamadas)
        self.assertIn((2025, 5, 2), chamadas)
        self.assertEqual(resumo["filmes_encontrados"], 2)
        self.assertEqual(resumo["particoes_geradas"], 1)

        keys = [call.kwargs["Key"] for call in mock_s3_client.put_object.call_args_list]
        self.assertTrue(any("year=2025/month=05" in key for key in keys))

    def test_carregar_tmdb_por_ano_respeita_max_total_paginas(self):
        chamadas = []

        def fake_buscar_por_ano_mes_func(ano, mes, api_key, page, sort_by, timeout, urlopen_func, max_retries):
            chamadas.append((ano, mes, page))
            return {
                "total_pages": 3,
                "results": [
                    {"id": f"{ano}-{mes}-{page}", "release_date": f"{ano}-{mes:02d}-10", "title": "A"},
                ],
            }

        mock_s3_client = MagicMock()

        resumo = carregar_tmdb_por_ano_e_salvar_sor(
            api_key="abc123",
            bucket_name="bucket-sor",
            ano_inicio=2024,
            ano_fim=2024,
            mes_inicio=1,
            mes_fim=2,
            paginas_por_ano=0,
            paginas_por_mes=0,
            max_total_paginas=2,
            s3_prefix="tmdb/discover_movie",
            s3_client=mock_s3_client,
            buscar_por_ano_mes_func=fake_buscar_por_ano_mes_func,
        )

        self.assertEqual(
            chamadas,
            [
                (2024, 1, 1),
                (2024, 1, 2),
                (2024, 2, 1),
                (2024, 2, 2),
            ],
        )
        self.assertEqual(resumo["paginas_processadas"], 4)
        self.assertEqual(resumo["paginas_processadas_por_mes"]["2024-01"], 2)
        self.assertEqual(resumo["paginas_processadas_por_mes"]["2024-02"], 2)
        self.assertEqual(resumo["filmes_encontrados"], 4)

    def test_carregar_tmdb_por_ano_retorna_cursor_quando_limita_meses(self):
        def fake_buscar_por_ano_mes_func(ano, mes, api_key, page, sort_by, timeout, urlopen_func, max_retries):
            return {
                "total_pages": 1,
                "results": [
                    {"id": f"{ano}-{mes}", "release_date": f"{ano}-{mes:02d}-10", "title": "A"},
                ],
            }

        mock_s3_client = MagicMock()

        resumo = carregar_tmdb_por_ano_e_salvar_sor(
            api_key="abc123",
            bucket_name="bucket-sor",
            ano_inicio=2025,
            ano_fim=2025,
            mes_inicio=1,
            mes_fim=4,
            max_meses_por_execucao=2,
            paginas_por_mes=1,
            s3_prefix="tmdb/discover_movie",
            s3_client=mock_s3_client,
            buscar_por_ano_mes_func=fake_buscar_por_ano_mes_func,
        )

        self.assertFalse(resumo["concluido"])
        self.assertEqual(resumo["meses_processados"], 2)
        self.assertEqual(resumo["proximo_cursor"]["ano_inicio"], 2025)
        self.assertEqual(resumo["proximo_cursor"]["mes_inicio"], 3)


if __name__ == "__main__":
    unittest.main()
    