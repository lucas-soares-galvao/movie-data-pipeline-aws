"""Testes unitarios das funcoes utilitarias."""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.glue_etl.src.utils import (
    chamar_glue_data_quality,
    eh_par,
    ler_arquivo_do_s3,
    escrever_arquivo_no_s3,
    processar_arquivo_etl,
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


class TestLerArquivoDoS3(unittest.TestCase):
    """Testa a funcionalidade de leitura de arquivos do S3."""

    def test_ler_arquivo_com_sucesso(self):
        """Testa a leitura bem-sucedida de um arquivo do S3."""
        mock_s3_client = MagicMock()
        mock_s3_client.get_object.return_value = {
            'Body': MagicMock(read=lambda: b'conteudo do arquivo')
        }

        conteudo = ler_arquivo_do_s3(
            bucket_name="test-bucket",
            s3_key="teste.txt",
            s3_client=mock_s3_client,
        )

        mock_s3_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="teste.txt"
        )
        self.assertEqual(conteudo, "conteudo do arquivo")

    def test_ler_arquivo_sem_cliente_s3(self):
        """Testa a leitura sem passar um cliente S3."""
        with patch("app.glue_etl.src.utils.import_module") as mock_import:
            mock_s3_client = MagicMock()
            mock_boto3 = MagicMock()
            mock_boto3.client.return_value = mock_s3_client
            mock_import.return_value = mock_boto3
            mock_s3_client.get_object.return_value = {
                'Body': MagicMock(read=lambda: b'conteudo')
            }

            conteudo = ler_arquivo_do_s3(
                bucket_name="test-bucket",
                s3_key="teste.txt",
            )

            mock_import.assert_called_once_with("boto3")
            mock_boto3.client.assert_called_once_with("s3")
            self.assertEqual(conteudo, "conteudo")


class TestEscreverArquivoNoS3(unittest.TestCase):
    """Testa a funcionalidade de escrita de arquivos no S3."""

    def test_escrever_arquivo_com_sucesso(self):
        """Testa a escrita bem-sucedida de um arquivo no S3."""
        mock_s3_client = MagicMock()

        resultado = escrever_arquivo_no_s3(
            bucket_name="test-bucket",
            s3_key="saida.txt",
            conteudo="conteudo para escrever",
            s3_client=mock_s3_client,
        )

        mock_s3_client.put_object.assert_called_once()
        call_kwargs = mock_s3_client.put_object.call_args[1]
        self.assertEqual(call_kwargs["Bucket"], "test-bucket")
        self.assertEqual(call_kwargs["Key"], "saida.txt")
        self.assertEqual(call_kwargs["Body"], b"conteudo para escrever")

        self.assertEqual(resultado["bucket"], "test-bucket")
        self.assertEqual(resultado["key"], "saida.txt")
        self.assertEqual(resultado["status"], "written")

    def test_escrever_arquivo_sem_cliente_s3(self):
        """Testa a escrita sem passar um cliente S3."""
        with patch("app.glue_etl.src.utils.import_module") as mock_import:
            mock_s3_client = MagicMock()
            mock_boto3 = MagicMock()
            mock_boto3.client.return_value = mock_s3_client
            mock_import.return_value = mock_boto3

            resultado = escrever_arquivo_no_s3(
                bucket_name="test-bucket",
                s3_key="saida.txt",
                conteudo="conteudo",
            )

            mock_import.assert_called_once_with("boto3")
            mock_boto3.client.assert_called_once_with("s3")
            self.assertEqual(resultado["status"], "written")


class TestProcessarArquivoETL(unittest.TestCase):
    """Testa a funcionalidade de processamento de arquivos."""

    def test_adiciona_header_de_processamento(self):
        """Testa se o arquivo recebe header indicando processamento."""
        conteudo_entrada = "teste"
        resultado = processar_arquivo_etl(conteudo_entrada)

        self.assertIn("[PROCESSADO PELO ETL]", resultado)
        self.assertIn("teste", resultado)

    def test_preserva_conteudo_original(self):
        """Testa se o conteúdo original é preservado."""
        conteudo_entrada = "dados importantes"
        resultado = processar_arquivo_etl(conteudo_entrada)

        self.assertTrue(resultado.endswith("dados importantes"))


if __name__ == "__main__":
    unittest.main()
    