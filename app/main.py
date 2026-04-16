"""Ponto de entrada da aplicacao usada no job de Glue."""

from app.src.utils import eh_par

def processar_numero(numero):
    """Encapsula a regra de negocio para facilitar reutilizacao e testes."""
    if eh_par(numero):
        return f"O número {numero} é par."
    else:
        return f"O número {numero} é ímpar."

def main():
    # Exemplo simples de execucao local do modulo.
    resultado = processar_numero(10)
    print(resultado)

if __name__ == "__main__":
    main()
    