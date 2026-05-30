"""Raciocinio: isola resolucao de imports entre suites para evitar conflito entre pacotes src homonimos."""

import sys
from pathlib import Path

_TEST_ROOT = Path(__file__).parent
_APP_ROOT = _TEST_ROOT.parent / "app"

_SUITE_TO_APP: dict[str, Path] = {
    "glue_data_quality": _APP_ROOT / "glue_data_quality",
    "glue_etl": _APP_ROOT / "glue_etl",
    "lambda_api": _APP_ROOT / "lambda_api",
}

# Subpacotes dentro de cada diretorio app que expoem um modulo src/utils.
_SUITE_TO_SRC_MODULE: dict[str, str] = {
    "glue_data_quality": "app.glue_data_quality.src.utils",
    "glue_etl": "app.glue_etl.src.utils",
    "lambda_api": "app.lambda_api.src.utils",
}


def pytest_collect_file(parent, file_path):  # noqa: ARG001
    """Re-scope sys.path and alias src.utils before each test file is imported."""
    try:
        suite = file_path.relative_to(_TEST_ROOT).parts[0]
    except (ValueError, IndexError):
        return

    app_dir = _SUITE_TO_APP.get(suite)
    if app_dir is None:
        return

    # Evict the cached 'src' and 'main' namespaces so the next import picks the right one.
    for key in list(sys.modules.keys()):
        if key == "src" or key.startswith("src.") or key == "main":
            del sys.modules[key]

    # Promote this suite's app directory to the front of sys.path.
    app_dir_str = str(app_dir)
    sys.path[:] = [app_dir_str] + [p for p in sys.path if p != app_dir_str]

    # Pre-import the fully-qualified utils module and alias it as 'src.utils'
    # so that patches on app.X.src.utils also affect code using
    # 'from src.utils import ...'.
    fq_module = _SUITE_TO_SRC_MODULE[suite]
    try:
        __import__(fq_module)
        mod = sys.modules[fq_module]
        sys.modules["src.utils"] = mod
        # Tambem expõe o pacote pai 'src' se ele estiver disponivel.
        src_pkg = fq_module.rsplit(".", 1)[0]  # app.X.src
        if src_pkg in sys.modules:
            sys.modules["src"] = sys.modules[src_pkg]
    except ImportError:
        pass
