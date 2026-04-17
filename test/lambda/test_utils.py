"""Testes unitarios das funcoes utilitarias."""

import os
import unittest
from unittest.mock import patch

from app.lambda_api.src.utils import chamar_glue_etl_e_data_quality, eh_par

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

    def start_job_run(self, JobName):
        self.calls.append(JobName)
        return {"JobRunId": f"run-{JobName}"}


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


if __name__ == "__main__":
    unittest.main()
    