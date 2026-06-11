"""
conftest.py — Configuração de testes para o Lambda lightsail_scheduler.

Adiciona app/lambda_lightsail_scheduler ao sys.path para que os testes
importem main.py diretamente, e define a variável de ambiente obrigatória
LIGHTSAIL_INSTANCE_NAME com um valor fictício de teste.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../app/lambda_lightsail_scheduler"))

os.environ.setdefault("LIGHTSAIL_INSTANCE_NAME", "test-instance")
