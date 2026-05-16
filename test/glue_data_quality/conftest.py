"""Stubs for AWS Glue and PySpark modules unavailable outside the Glue runtime."""

import sys
import types
from pathlib import Path

# Allow 'from src.X import ...' to resolve against app/glue_data_quality/src/
# as it would in the Glue runtime bundle.
_app_dir = Path(__file__).parents[2] / "app" / "glue_data_quality"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


def _make_module(name, **attrs):
    mod = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(mod, attr, value)
    return mod


# awsglue stubs
sys.modules.setdefault("awsglue", _make_module("awsglue"))
sys.modules.setdefault(
    "awsglue.utils",
    _make_module("awsglue.utils", getResolvedOptions=None),
)
sys.modules.setdefault("awsglue.context", _make_module("awsglue.context", GlueContext=None))

# awsgluedq stubs
sys.modules.setdefault("awsgluedq", _make_module("awsgluedq"))
sys.modules.setdefault(
    "awsgluedq.transforms",
    _make_module("awsgluedq.transforms", EvaluateDataQuality=None),
)

# pyspark stubs
sys.modules.setdefault("pyspark", _make_module("pyspark"))
sys.modules.setdefault("pyspark.context", _make_module("pyspark.context", SparkContext=None))
sys.modules.setdefault("pyspark.sql", _make_module("pyspark.sql"))
sys.modules.setdefault(
    "pyspark.sql.functions",
    _make_module("pyspark.sql.functions", lit=None),
)
