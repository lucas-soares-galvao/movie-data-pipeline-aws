"""Testes do modulo principal da aplicacao."""

import unittest
from unittest.mock import patch

from app.glue_etl.main import main, processar_numero

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
    @patch("app.glue_etl.main.chamar_glue_data_quality")
    def test_main_dispara_data_quality_na_ultima_etapa(self, mock_chamar_dq, mock_print):
        mock_chamar_dq.return_value = {
            "data_quality_job_name": "dq-job",
            "data_quality_job_run_id": "jr-abc",
        }

        main()

        mock_chamar_dq.assert_called_once_with()
        self.assertEqual(mock_print.call_count, 2)

if __name__ == '__main__':
    unittest.main()
    