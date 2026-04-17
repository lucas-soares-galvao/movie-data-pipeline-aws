"""Testes unitarios das funcoes utilitarias."""

import os
import unittest
from unittest.mock import patch

from app.glue_etl.src.utils import chamar_glue_data_quality, eh_par

class TestEhPar(unittest.TestCase):
    """Garante que a classificacao de numeros pares/impares esteja correta."""

    def test_numero_par_retorna_true(self):
        self.assertTrue(eh_par(2))
        self.assertTrue(eh_par(0))
        self.assertTrue(eh_par(-4))

    def test_numero_impar_retorna_false(self):
        self.assertFalse(eh_par(1))
        self.assertFalse(eh_par(-3))


class _FakeGlueClient:
    def __init__(self):
        self.calls = []

    def start_job_run(self, **kwargs):
        self.calls.append(kwargs)
        return {"JobRunId": "run-dq"}


class TestChamarGlueDataQuality(unittest.TestCase):
    def test_dispara_job_com_argumentos(self):
        fake_client = _FakeGlueClient()

        result = chamar_glue_data_quality(
            data_quality_job_name="dq-job",
            glue_client=fake_client,
            job_arguments={"--env": "dev"},
        )

        self.assertEqual(fake_client.calls[0]["JobName"], "dq-job")
        self.assertEqual(fake_client.calls[0]["Arguments"], {"--env": "dev"})
        self.assertEqual(result["data_quality_job_run_id"], "run-dq")

    def test_dispara_job_sem_argumentos(self):
        fake_client = _FakeGlueClient()

        result = chamar_glue_data_quality(
            data_quality_job_name="dq-job",
            glue_client=fake_client,
        )

        self.assertEqual(fake_client.calls[0], {"JobName": "dq-job"})
        self.assertEqual(result["data_quality_job_name"], "dq-job")

    def test_falha_quando_nome_job_nao_informado(self):
        fake_client = _FakeGlueClient()

        with self.assertRaises(ValueError):
            chamar_glue_data_quality(
                data_quality_job_name=None,
                glue_client=fake_client,
            )

    def test_usa_nome_job_vindo_do_ambiente(self):
        fake_client = _FakeGlueClient()

        with patch.dict(
            os.environ,
            {"GLUE_DATA_QUALITY_JOB_NAME": "dq-job-env"},
            clear=True,
        ):
            result = chamar_glue_data_quality(
                data_quality_job_name=None,
                glue_client=fake_client,
            )

        self.assertEqual(fake_client.calls[0], {"JobName": "dq-job-env"})
        self.assertEqual(result["data_quality_job_name"], "dq-job-env")


if __name__ == "__main__":
    unittest.main()
    