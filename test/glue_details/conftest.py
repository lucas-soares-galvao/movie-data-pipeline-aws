"""
conftest.py — Configuração de testes para o módulo Glue Details.

==============================================================================
POR QUE PRECISAMOS DESTE conftest.py?
==============================================================================
O código do Glue Details importa bibliotecas do AWS Glue:
  from awsglue.utils import getResolvedOptions

Essas bibliotecas SÓ EXISTEM no runtime do AWS Glue (ambiente cloud).
Para rodar os testes localmente, precisamos simular esses módulos.

SOLUÇÃO: Mesma abordagem dos outros módulos Glue — registrar stubs em
sys.modules antes que qualquer import real seja tentado.

Raciocinio: prepara mocks do runtime Glue para testar Details localmente com previsibilidade.
"""

import sys
import os
from unittest.mock import MagicMock
from types import ModuleType

# Adiciona app/glue_details/ ao início de sys.path para que
# "from src.utils import ..." funcione nos testes
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "app", "glue_details")
)

# Registra módulo stub para o SDK do AWS Glue
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))
awsglue_utils_module = sys.modules.setdefault(
    "awsglue.utils", ModuleType("awsglue.utils")
)
# getResolvedOptions é o método do Glue que lê os argumentos "--KEY valor" do job.
# Nos testes, substituímos por MagicMock() para retornar valores que controlamos.
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_utils_module.GlueArgumentError = Exception  # exceção lançada por args faltando
awsglue_module.utils = awsglue_utils_module
