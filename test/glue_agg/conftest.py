"""
conftest.py — Configuração de testes para o módulo Glue AGG.

==============================================================================
POR QUE PRECISAMOS DESTE conftest.py?
==============================================================================
O código do Glue AGG importa bibliotecas do AWS Glue (awsglue):
  from awsglue.utils import getResolvedOptions

Essas bibliotecas SÓ EXISTEM dentro do runtime do AWS Glue.
Em um ambiente local ou CI/CD, um simples "import awsglue" falharia.

SOLUÇÃO: Registrar módulos "stub" (esqueletos vazios) em sys.modules
ANTES que o código tente importar, para que Python encontre o stub
em vez de procurar o pacote real (que não existe localmente).

Raciocinio: prepara mocks do runtime Glue para testar AGG localmente com previsibilidade.
"""

import sys
from unittest.mock import MagicMock
from types import ModuleType

# Cria e registra o módulo stub para "awsglue" — pacote raiz do AWS Glue SDK
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))

# Cria e registra o stub para "awsglue.utils" com os atributos que o código usa:
#   - getResolvedOptions: substituído por MagicMock() para ser configurável nos testes
#   - GlueArgumentError: usada como tipo de exceção (usamos Exception como substituto)
awsglue_utils_module = sys.modules.setdefault(
    "awsglue.utils", ModuleType("awsglue.utils")
)
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_utils_module.GlueArgumentError = Exception
awsglue_module.utils = awsglue_utils_module  # conecta o submódulo ao pacote pai
