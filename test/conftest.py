"""Raciocinio: isola resolucao de imports entre suites para evitar conflito entre pacotes src homonimos."""

import sys
from pathlib import Path

_TEST_ROOT = Path(__file__).parent
_APP_ROOT = _TEST_ROOT.parent / "app"

_SUITE_TO_APP: dict[str, Path] = {
    "glue_agg": _APP_ROOT / "glue_agg",
    "glue_data_quality": _APP_ROOT / "glue_data_quality",
    "glue_etl": _APP_ROOT / "glue_etl",
    "lambda_api": _APP_ROOT / "lambda_api",
}

# Subpacotes dentro de cada diretorio app que expoem um modulo src/utils.
_SUITE_TO_SRC_MODULE: dict[str, str] = {
    "glue_agg": "app.glue_agg.src.utils",
    "glue_data_quality": "app.glue_data_quality.src.utils",
    "glue_etl": "app.glue_etl.src.utils",
    "lambda_api": "app.lambda_api.src.utils",
}

# Conjunto de todos os diretórios de app e src conhecidos — usado para limpar sys.path
# antes de promover a suite corrente, evitando que caminhos de outras suites vazar.
_ALL_APP_DIRS: frozenset[str] = frozenset(str(p) for p in _SUITE_TO_APP.values())
_ALL_SRC_DIRS: frozenset[str] = frozenset(
    str(p / "src") for p in _SUITE_TO_APP.values()
)


def _set_suite_path(app_dir: Path) -> None:
    """Coloca src/ e app_dir da suite no topo de sys.path, removendo todas as outras suites."""
    app_dir_str = str(app_dir)
    src_dir_str = str(app_dir / "src")
    sys.path[:] = [src_dir_str, app_dir_str] + [
        p for p in sys.path if p not in _ALL_APP_DIRS and p not in _ALL_SRC_DIRS
    ]


def pytest_collect_file(parent, file_path):  # noqa: ARG001
    """Re-scope sys.path and alias src.utils before each test file is imported."""
    try:
        suite = file_path.relative_to(_TEST_ROOT).parts[0]
    except (ValueError, IndexError):
        return

    app_dir = _SUITE_TO_APP.get(suite)
    if app_dir is None:
        return

    # Evict the cached 'src', 'main', and flat 'utils' namespaces so the next import
    # picks the right module for this suite.  'utils' is registered as a top-level
    # module when main.py does 'from utils import ...', so it must also be cleared.
    for key in list(sys.modules.keys()):
        if key in ("src", "main", "utils") or key.startswith("src."):
            del sys.modules[key]

    # Promote this suite's app directory (and its src/ sub-dir) to the front of sys.path,
    # stripping all other suites' directories so they cannot shadow the active one.
    _set_suite_path(app_dir)

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
            # Alias all sub-modules (e.g., src.rulesets_dq) so inline imports work.
            prefix = src_pkg + "."
            for key in list(sys.modules.keys()):
                if key.startswith(prefix):
                    sys.modules["src." + key[len(prefix) :]] = sys.modules[key]
    except ImportError:
        pass


def _apply_suite_aliases(suite: str) -> None:
    """Re-alias sys.modules src.* entries to the correct suite's modules."""
    fq_module = _SUITE_TO_SRC_MODULE.get(suite)
    if not fq_module or fq_module not in sys.modules:
        return

    sys.modules["src.utils"] = sys.modules[fq_module]
    src_pkg = fq_module.rsplit(".", 1)[0]  # app.X.src
    if src_pkg in sys.modules:
        sys.modules["src"] = sys.modules[src_pkg]
        prefix = src_pkg + "."
        for key in list(sys.modules.keys()):
            if key.startswith(prefix):
                sys.modules["src." + key[len(prefix) :]] = sys.modules[key]

    _set_suite_path(_SUITE_TO_APP[suite])


def pytest_runtest_setup(item):
    """Re-alias src.* to the correct suite modules before each test executes."""
    try:
        suite = item.path.relative_to(_TEST_ROOT).parts[0]
    except (ValueError, IndexError):
        return

    if suite in _SUITE_TO_SRC_MODULE:
        _apply_suite_aliases(suite)
