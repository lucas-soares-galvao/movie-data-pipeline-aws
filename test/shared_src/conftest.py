import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_shared_dir = Path(__file__).parents[2] / "app" / "shared_src"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

# Stub do AWS Glue SDK — não existe fora do runtime do Glue
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))
awsglue_utils_module = sys.modules.setdefault("awsglue.utils", ModuleType("awsglue.utils"))
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_module.utils = awsglue_utils_module


@pytest.fixture(autouse=True)
def _isola_segredos_registrados():
    """Os segredos registrados para mascaramento (shared_utils.secret_redaction) são estado global
    do processo: sem limpar, o valor registrado por um teste mascararia texto de outro."""
    from shared_utils import secret_redaction

    secret_redaction._secrets.clear()
    yield
    secret_redaction._secrets.clear()
