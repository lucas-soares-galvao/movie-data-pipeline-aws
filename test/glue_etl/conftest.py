"""Raciocinio: prepara mocks do runtime Glue para testar ETL localmente com previsibilidade."""

import sys
import os
from unittest.mock import MagicMock
from types import ModuleType

# Allows Glue job modules to resolve 'src.utils' as in the AWS Glue runtime.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app", "glue_etl"))

# Mock AWS Glue libraries unavailable outside the Glue runtime.
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))
awsglue_utils_module = sys.modules.setdefault("awsglue.utils", ModuleType("awsglue.utils"))
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_module.utils = awsglue_utils_module
