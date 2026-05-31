"""Raciocinio: prepara mocks do runtime Glue para testar AGG localmente com previsibilidade."""

import sys
import os
from unittest.mock import MagicMock
from types import ModuleType

# Permite que os modulos do job Glue resolvam 'src.utils' como no runtime do AWS Glue.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app", "glue_agg"))

# Simula bibliotecas do AWS Glue que nao estao disponiveis fora do runtime.
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))
awsglue_utils_module = sys.modules.setdefault("awsglue.utils", ModuleType("awsglue.utils"))
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_module.utils = awsglue_utils_module
