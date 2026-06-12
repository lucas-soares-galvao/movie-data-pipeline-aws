"""Stubs do AWS Glue SDK (awsglue não existe fora do runtime do Glue)."""

import sys
from unittest.mock import MagicMock
from types import ModuleType

awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))

# getResolvedOptions vira MagicMock() para ser configurável nos testes;
# GlueArgumentError usa Exception como substituto simples
awsglue_utils_module = sys.modules.setdefault(
    "awsglue.utils", ModuleType("awsglue.utils")
)
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_utils_module.GlueArgumentError = Exception
awsglue_module.utils = awsglue_utils_module  # conecta o submódulo ao pacote pai
