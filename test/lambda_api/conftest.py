import sys
import os

# Adiciona app/lambda_api ao sys.path para que os imports relativos (from src.utils)
# dentro de main.py funcionem durante os testes, assim como funcionam no Lambda.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app", "lambda_api"))
