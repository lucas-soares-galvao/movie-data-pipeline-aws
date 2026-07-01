import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

_shared_dir = Path(__file__).parents[2] / "app" / "shared_src"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

# Stub do AWS Glue SDK — não existe fora do runtime do Glue
awsglue_module = sys.modules.setdefault("awsglue", ModuleType("awsglue"))
awsglue_utils_module = sys.modules.setdefault("awsglue.utils", ModuleType("awsglue.utils"))
awsglue_utils_module.getResolvedOptions = MagicMock()
awsglue_module.utils = awsglue_utils_module
