"""Stubs do AWS Glue SDK (awsglue não existe fora do runtime do Glue)."""

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

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


@pytest.fixture(autouse=True)
def _clear_aws_account_id(monkeypatch):
    """Isola AWS_ACCOUNT_ID entre testes.

    get_parameters_glue publica AWS_ACCOUNT_ID em os.environ (via getResolvedOptions),
    o que vazaria entre testes e faria as asserções de get_object/put_object que não
    esperam ExpectedBucketOwner falharem conforme a ordem de execução.
    """
    monkeypatch.delenv("AWS_ACCOUNT_ID", raising=False)
