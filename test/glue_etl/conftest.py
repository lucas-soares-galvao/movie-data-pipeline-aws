"""
conftest.py — Configuração de testes para o módulo Glue ETL.

==============================================================================
POR QUE PRECISAMOS DESTE conftest.py?
==============================================================================
O código do Glue ETL importa bibliotecas do AWS Glue (awsglue):
  from awsglue.utils import getResolvedOptions

Essas bibliotecas SÓ EXISTEM dentro do runtime do AWS Glue (no cluster cloud).
Em um computador local ou no CI/CD, elas não estão instaladas — um simples
"import awsglue" falharia com "ModuleNotFoundError".

SOLUÇÃO: Criar módulos "fantasma" (stubs/mocks) que fingem ser as bibliotecas
reais. O Python aceita esses módulos falsos porque registramos em sys.modules
antes que qualquer código tente fazer o import real.

ANALOGIA: Como um "dublê de ator". O awsglue real não está disponível,
então colocamos um dublê que tem a mesma aparência (mesmo nome de funções)
mas não faz nada de verdade — apenas retorna MagicMock() para que os testes
possam controlar o comportamento.

O QUE ESTE conftest FAZ:
  1. Adiciona app/glue_etl/ ao sys.path para que "from src.utils import ..."
     funcione nos testes (idêntico ao runtime do Glue)
  2. Registra módulos stub para awsglue e awsglue.utils em sys.modules
  3. getResolvedOptions é substituído por um MagicMock() controlável nos testes

Raciocinio: prepara mocks do runtime Glue para testar ETL localmente com previsibilidade.
"""

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
