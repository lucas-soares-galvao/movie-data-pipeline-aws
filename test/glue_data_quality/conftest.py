"""Raciocinio: simula dependencias Glue/PySpark para executar testes fora do runtime AWS."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Permite que 'from src.X import ...' resolva para app/glue_data_quality/src/
# como ocorreria no pacote de runtime do Glue.
_app_dir = Path(__file__).parents[2] / "app" / "glue_data_quality"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


def _make_module(name, **attrs):
    mod = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(mod, attr, value)
    return mod


# stubs do awsglue
sys.modules.setdefault("awsglue", _make_module("awsglue"))
sys.modules.setdefault(
    "awsglue.utils",
    _make_module("awsglue.utils", getResolvedOptions=None),
)
sys.modules.setdefault(
    "awsglue.context", _make_module("awsglue.context", GlueContext=None)
)
sys.modules.setdefault(
    "awsglue.dynamicframe", _make_module("awsglue.dynamicframe", DynamicFrame=None)
)

# stubs do awsgluedq
sys.modules.setdefault("awsgluedq", _make_module("awsgluedq"))
sys.modules.setdefault(
    "awsgluedq.transforms",
    _make_module("awsgluedq.transforms", EvaluateDataQuality=None),
)

# stubs do pyspark
sys.modules.setdefault("pyspark", _make_module("pyspark"))
sys.modules.setdefault(
    "pyspark.context", _make_module("pyspark.context", SparkContext=None)
)
sys.modules.setdefault("pyspark.sql", _make_module("pyspark.sql"))
sys.modules.setdefault(
    "pyspark.sql.functions",
    _make_module(
        "pyspark.sql.functions",
        coalesce=None,
        col=None,
        from_utc_timestamp=None,
        lit=None,
        current_timestamp=None,
        when=None,
    ),
)
sys.modules.setdefault(
    "pyspark.sql.types",
    _make_module("pyspark.sql.types", StringType=MagicMock()),
)
