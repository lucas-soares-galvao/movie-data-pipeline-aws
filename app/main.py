from app.src.utils import eh_par

def processar_numero(numero):
    """Encapsulamos a lógica para ser testável"""
    if eh_par(numero):
        return f"O número {numero} é par."
    else:
        return f"O número {numero} é ímpar."

def main():
    resultado = processar_numero(10)
    print(resultado)

if __name__ == "__main__":
    main()
    