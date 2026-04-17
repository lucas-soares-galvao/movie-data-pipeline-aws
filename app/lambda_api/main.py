"""Ponto de entrada da Lambda de exemplo."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from src.utils import eh_par

def processar_numero(numero):
    """Encapsula a regra de negocio para facilitar reutilizacao e testes."""
    if eh_par(numero):
        return f"O número {numero} é par."
    else:
        return f"O número {numero} é ímpar."


def lambda_handler(event, context):
    """Handler simples para execucao da Lambda."""
    numero = event.get("numero", 10)
    mensagem = processar_numero(numero)

    return {
        "statusCode": 200,
        "body": {
            "mensagem": mensagem,
            "numero": numero,
        },
    }

def main():
    # Exemplo simples de execucao local do modulo.
    resultado = processar_numero(10)
    print(resultado)

if __name__ == "__main__":
    main()