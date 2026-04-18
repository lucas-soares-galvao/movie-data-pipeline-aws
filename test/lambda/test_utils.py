"""Testes unitarios das funcoes utilitarias."""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.lambda_api.src.utils import (
    chamar_glue_etl_e_data_quality,
    eh_par,
    upload_arquivo_para_s3,
)

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


class TestUploadArquivoParaS3(unittest.TestCase):
    """Testa a funcionalidade de upload de arquivos para S3."""

    def test_upload_arquivo_com_sucesso(self):
        """Testa o upload bem-sucedido de um arquivo para S3."""
        # Cria um arquivo temporário para teste
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("conteudo de teste")
            temp_file = f.name

        try:
            # Mock do cliente S3
            mock_s3_client = MagicMock()

            # Executa o upload
            result = upload_arquivo_para_s3(
                bucket_name="test-bucket",
                file_path=temp_file,
                s3_key="teste.txt",
                s3_client=mock_s3_client,
            )

            # Verifica se o método put_object foi chamado com os parâmetros corretos
            mock_s3_client.put_object.assert_called_once()
            call_kwargs = mock_s3_client.put_object.call_args[1]
            self.assertEqual(call_kwargs["Bucket"], "test-bucket")
            self.assertEqual(call_kwargs["Key"], "teste.txt")

            # Verifica o resultado retornado
            self.assertEqual(result["bucket"], "test-bucket")
            self.assertEqual(result["key"], "teste.txt")
            self.assertEqual(result["status"], "uploaded")
        finally:
            # Remove o arquivo temporário
            os.unlink(temp_file)

    def test_upload_arquivo_sem_cliente_s3(self):
        """Testa o upload sem passar um cliente S3 (cria automaticamente)."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("conteudo de teste")
            temp_file = f.name

        try:
            with patch("app.lambda_api.src.utils.import_module") as mock_import:
                mock_s3_client = MagicMock()
                mock_boto3 = MagicMock()
                mock_boto3.client.return_value = mock_s3_client
                mock_import.return_value = mock_boto3

                result = upload_arquivo_para_s3(
                    bucket_name="test-bucket",
                    file_path=temp_file,
                    s3_key="teste.txt",
                )

                # Verifica se boto3 foi importado e o cliente foi criado
                mock_import.assert_called_once_with("boto3")
                mock_boto3.client.assert_called_once_with("s3")

                # Verifica o resultado
                self.assertEqual(result["status"], "uploaded")
        finally:
            os.unlink(temp_file)


if __name__ == "__main__":
    unittest.main()
    