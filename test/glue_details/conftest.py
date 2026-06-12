"""Stubs do AWS Glue SDK (awsglue não existe fora do runtime do Glue)."""

import sys
import os
from unittest.mock import MagicMock
from types import ModuleType

# Adiciona app/glue_details/ ao início de sys.path para que
# "from src.utils import ..." funcione nos testes
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "app", "glue_details")
)

awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))
awsglue_utils_module = sys.modules.setdefault(
    "awsglue.utils", ModuleType("awsglue.utils")
)
# getResolvedOptions é o método do Glue que lê os argumentos "--KEY valor" do job.
# Nos testes, substituímos por MagicMock() para retornar valores que controlamos.
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_utils_module.GlueArgumentError = Exception  # exceção lançada por args faltando
awsglue_module.utils = awsglue_utils_module
