"""Testes do modulo principal da aplicacao."""

import os
import unittest
from unittest.mock import patch, MagicMock

from app.glue_etl.main import (
    main,
    obter_arg_data_quality_job_name,
    processar_numero,
    processar_arquivo_sor_para_sot,
)

class TestMain(unittest.TestCase):
    """Valida as mensagens retornadas pela funcao processar_numero."""

    def test_processar_numero_par(self):
        # Testa a lógica para um número par
        esperado = "O número 10 é par."
        resultado = processar_numero(10)
        self.assertEqual(resultado, esperado)

    def test_processar_numero_impar(self):
        # Testa a lógica para um número ímpar
        esperado = "O número 7 é ímpar."
        resultado = processar_numero(7)
        self.assertEqual(resultado, esperado)

    @patch("app.glue_etl.main.print")
    @patch(
        "app.glue_etl.main.sys.argv",
        [
            "main.py",
            "--GLUE_DATA_QUALITY_JOB_NAME",
            "dq-job",
            "--S3_BUCKET_SOR",
            "lsg-sa-east-1-bucket-sor-dev",
            "--S3_BUCKET_SOT",
            "lsg-sa-east-1-bucket-sot-dev",
        ],
    )
    @patch("app.glue_etl.main.processar_arquivo_sor_para_sot")
    @patch("app.glue_etl.main.chamar_glue_data_quality")
    def test_main_dispara_data_quality_na_ultima_etapa(self, mock_chamar_dq, mock_processar_arquivo, mock_print):
        mock_processar_arquivo.return_value = {
            "bucket": "sot-bucket",
            "key": "teste_processado.txt",
            "status": "written"
        }
        mock_chamar_dq.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-abc",
        }

        main()

        mock_processar_arquivo.assert_called_once()
        mock_chamar_dq.assert_called_once_with(data_quality_job_name="dq-job")
        self.assertEqual(mock_print.call_count, 3)  # Número, resultado ETL, resultado DQ

    def test_obter_arg_data_quality_job_name_quando_presente(self):
        argv = ["main.py", "--GLUE_DATA_QUALITY_JOB_NAME", "dq-job"]
        self.assertEqual(obter_arg_data_quality_job_name(argv), "dq-job")

    def test_obter_arg_data_quality_job_name_quando_ausente(self):
        argv = ["main.py", "--outra-flag", "valor"]
        self.assertIsNone(obter_arg_data_quality_job_name(argv))

    @patch("app.glue_etl.main.escrever_arquivo_no_s3")
    @patch("app.glue_etl.main.ler_arquivo_do_s3")
    def test_processar_arquivo_sor_para_sot_com_sucesso(self, mock_ler, mock_escrever):
        """Testa o processamento bem-sucedido do arquivo SOR para SOT."""
        mock_ler.return_value = "conteudo original"
        mock_escrever.return_value = {
            "bucket": "sot-bucket",
            "key": "teste_processado.txt",
            "status": "written"
        }

        resultado = processar_arquivo_sor_para_sot(
            s3_bucket_sor="sor-bucket",
            s3_bucket_sot="sot-bucket",
            s3_key_entrada="teste.txt",
            s3_key_saida="teste_processado.txt"
        )

        # Verifica se leu do SOR
        mock_ler.assert_called_once_with(
            bucket_name="sor-bucket",
            s3_key="teste.txt"
        )

        # Verifica se escreveu no SOT
        mock_escrever.assert_called_once()
        call_kwargs = mock_escrever.call_args[1]
        self.assertEqual(call_kwargs["bucket_name"], "sot-bucket")
        self.assertEqual(call_kwargs["s3_key"], "teste_processado.txt")
        self.assertIn("[PROCESSADO PELO ETL]", call_kwargs["conteudo"])

        # Verifica resultado
        self.assertEqual(resultado["status"], "written")

if __name__ == '__main__':
    unittest.main()
    