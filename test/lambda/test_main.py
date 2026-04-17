"""Testes do modulo principal da aplicacao."""

import unittest
from app.lambda_api.main import processar_numero

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

if __name__ == '__main__':
    unittest.main()
    