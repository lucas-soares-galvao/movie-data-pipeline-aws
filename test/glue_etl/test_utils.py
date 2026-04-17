"""Testes unitarios das funcoes utilitarias."""

from app.glue_etl.src.utils import eh_par
import unittest

class TestEhPar(unittest.TestCase):
    """Garante que a classificacao de numeros pares/impares esteja correta."""

    def test_numero_par_retorna_true(self):
        self.assertTrue(eh_par(2))
        self.assertTrue(eh_par(0))
        self.assertTrue(eh_par(-4))

    def test_numero_impar_retorna_false(self):
        self.assertFalse(eh_par(1))
        self.assertFalse(eh_par(-3))


if __name__ == "__main__":
    unittest.main()
    