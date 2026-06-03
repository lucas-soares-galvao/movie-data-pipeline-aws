"""Raciocinio: prepara mocks do runtime Glue para testar AGG localmente com previsibilidade."""

import sys
from unittest.mock import MagicMock
from types import ModuleType

# Simula bibliotecas do AWS Glue que nao estao disponiveis fora do runtime.
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))
awsglue_utils_module = sys.modules.setdefault(
    "awsglue.utils", ModuleType("awsglue.utils")
)
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_utils_module.GlueArgumentError = Exception
awsglue_module.utils = awsglue_utils_module
