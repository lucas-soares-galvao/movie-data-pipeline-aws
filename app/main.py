from src.utils import eh_par

def main():
    numero = 10
    if eh_par(numero):
        print(f"O número {numero} é par.")
    else:
        print(f"O número {numero} é ímpar.")