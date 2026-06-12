"""
conftest.py — Configuração de testes para o módulo Glue Data Quality.

Stubs para awsglue, awsgluedq e pyspark (nenhum deles existe fora do runtime AWS/Glue).
Atenção: funções PySpark como col() e when() precisam ser MagicMock() — não None —
porque o código as chama diretamente. None causaria "NoneType is not callable".
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Adiciona app/glue_data_quality/ ao sys.path para que
# "from src.utils import ..." e "from src.rulesets_dq import ..." funcionem
_app_dir = Path(__file__).parents[2] / "app" / "glue_data_quality"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


def _make_module(name, **attrs):
    """
    Cria um módulo Python vazio com atributos personalizados.

    Esta função de conveniência reduz a verbosidade de criar e configurar
    módulos stub manualmente.

    Args:
        name:  Nome do módulo (usado apenas para identificação).
        attrs: Dicionário de atributos a definir no módulo.

    Returns:
        ModuleType configurado com os atributos fornecidos.
    """
    mod = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(mod, attr, value)
    return mod


# ==============================================================================
# STUBS DO AWS GLUE SDK (awsglue)
# ==============================================================================
# setdefault() só registra se o módulo ainda não estiver em sys.modules,
# evitando substituir um pacote real caso os testes rodem no ambiente do Glue.

sys.modules.setdefault("awsglue", _make_module("awsglue"))
sys.modules.setdefault(
    "awsglue.utils",
    _make_module(
        "awsglue.utils",
        getResolvedOptions=None,   # substituído por MagicMock nos testes individuais
        GlueArgumentError=Exception,
    ),
)
sys.modules.setdefault(
    "awsglue.context",
    _make_module("awsglue.context", GlueContext=None),
)
sys.modules.setdefault(
    "awsglue.dynamicframe",
    _make_module("awsglue.dynamicframe", DynamicFrame=None),
)

# ==============================================================================
# STUBS DO MOTOR DE DATA QUALITY (awsgluedq)
# ==============================================================================
sys.modules.setdefault("awsgluedq", _make_module("awsgluedq"))
sys.modules.setdefault(
    "awsgluedq.transforms",
    _make_module("awsgluedq.transforms", EvaluateDataQuality=None),
)

# ==============================================================================
# STUBS DO APACHE SPARK (pyspark)
# ==============================================================================
# As funções SQL do PySpark (col, when, lit, etc.) precisam ser MagicMock()
# porque o código as CHAMA e encadeia (ex: col("year") == year).
# Se fossem None, o código falharia com "NoneType is not callable".
sys.modules.setdefault("pyspark", _make_module("pyspark"))
sys.modules.setdefault(
    "pyspark.context",
    _make_module("pyspark.context", SparkContext=None),
)
sys.modules.setdefault("pyspark.sql", _make_module("pyspark.sql"))
sys.modules.setdefault(
    "pyspark.sql.functions",
    _make_module(
        "pyspark.sql.functions",
        coalesce=None,
        col=MagicMock(),              # col("coluna") é chamada diretamente no código
        from_utc_timestamp=None,
        lit=None,
        current_timestamp=None,
        when=MagicMock(),             # when(condição).when(...) encadeia chamadas
    ),
)
sys.modules.setdefault(
    "pyspark.sql.types",
    _make_module("pyspark.sql.types", StringType=MagicMock()),  # StringType() é instanciado
)
