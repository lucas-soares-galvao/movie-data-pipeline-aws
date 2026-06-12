"""Stubs do AWS Glue SDK (awsglue não existe fora do runtime do Glue)."""

import sys
import os
from unittest.mock import MagicMock
from types import ModuleType

# Adiciona app/glue_etl/ ao início de sys.path.
# Isso permite que os módulos do job usem "from src.utils import ..."
# da mesma forma que no runtime do AWS Glue.
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "app", "glue_etl")
)

# Cria um módulo stub para "awsglue" e registra em sys.modules.
# sys.modules.setdefault() só registra se o módulo ainda não estiver lá —
# evita substituir um módulo real se os testes rodarem dentro do Glue.
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))

# Cria um módulo stub para "awsglue.utils" com as funções que o código usa:
#   - getResolvedOptions: lê argumentos do job no Glue (aqui vira MagicMock controlável)
#   - GlueArgumentError: exceção lançada quando um argumento está faltando
awsglue_utils_module = sys.modules.setdefault(
    "awsglue.utils", ModuleType("awsglue.utils")
)
awsglue_utils_module.getResolvedOptions = MagicMock()  # controlável nos testes
awsglue_utils_module.GlueArgumentError = Exception     # usa Exception como substituto simples
awsglue_module.utils = awsglue_utils_module            # conecta awsglue.utils ao módulo pai
