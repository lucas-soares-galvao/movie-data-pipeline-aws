"""
conftest.py — Configuração de testes para o Lambda lightsail_scheduler.

Define a variável de ambiente obrigatória LIGHTSAIL_INSTANCE_NAME e registra
o módulo do scheduler em sys.modules sob o nome único
"lambda_lightsail_scheduler_main".

Por que nome único em vez de "main"?
  O projeto tem vários main.py (lambda_api, glue_etl, etc.) e o pytest
  usa um único sys.modules compartilhado para toda a sessão de testes.
  Registrar sob "main" sobrescreveria o main.py de outra suite e quebraria
  seus testes. Um nome único isola completamente o módulo.
"""

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("LIGHTSAIL_INSTANCE_NAME", "test-instance")

_SCHEDULER_PATH = Path(__file__).resolve().parent.parent.parent / "app" / "lambda_lightsail_scheduler"

_spec = importlib.util.spec_from_file_location(
    "lambda_lightsail_scheduler_main",
    _SCHEDULER_PATH / "main.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["lambda_lightsail_scheduler_main"] = _mod
