# Raciocinio: scripts/ ja esta no pythonpath (pytest.ini), entao os testes
# importam os modulos de backfill diretamente (ex.: "import backfill_historico").

import sys
from types import ModuleType
from unittest.mock import MagicMock

# backfill_enriquecimento.py importa "from src.utils import ..." (mesmo pacote usado
# pelo job Glue Details, ver app/glue_details/src/utils.py) — que por sua vez importa
# shared_utils.glue_helpers.get_resolved_option, dependente de awsglue.utils. awsglue só
# existe no runtime do Glue; stub igual ao usado em test/glue_details/conftest.py.
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))
awsglue_utils_module = sys.modules.setdefault("awsglue.utils", ModuleType("awsglue.utils"))
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_utils_module.GlueArgumentError = Exception
awsglue_module.utils = awsglue_utils_module
