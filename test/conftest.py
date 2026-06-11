"""
conftest.py — Configuração global de testes (raiz do diretório test/).

==============================================================================
O QUE É UM conftest.py?
==============================================================================
O pytest procura arquivos conftest.py automaticamente antes de rodar os testes.
O conftest.py é o lugar para:
  - Definir "fixtures" (objetos reutilizáveis nos testes, como mocks e dados)
  - Configurar o ambiente de testes antes de cada arquivo/teste
  - Customizar o comportamento do pytest via hooks (funções especiais do pytest)

ESTE conftest.py ESPECÍFICO resolve um problema de importação:
  O projeto tem múltiplos módulos com a mesma estrutura interna:
    app/lambda_api/src/utils.py
    app/glue_etl/src/utils.py
    app/glue_agg/src/utils.py
    ...
  Todos esses módulos têm um "src.utils" — mas são arquivos diferentes!
  Python não consegue ter dois módulos com o mesmo nome em cache ao mesmo tempo.

PROBLEMA SEM ESTA SOLUÇÃO:
  Se você rodar os testes de lambda_api e depois os de glue_etl na mesma sessão,
  o Python usaria o "src.utils" cacheado da lambda_api para os testes do glue_etl.
  Isso causaria erros misteriosos e testes passando/falhando no lugar errado.

SOLUÇÃO IMPLEMENTADA:
  Antes de cada arquivo de teste, este conftest:
  1. Remove do cache (sys.modules) os módulos src.* que estão lá
  2. Coloca o diretório correto da suite no início de sys.path
  3. Registra o módulo correto (ex: app.glue_etl.src.utils) como alias "src.utils"

ANALOGIA: Como trocar os "óculos" antes de ler cada documento diferente.
  Cada suite de testes precisa de "óculos" diferentes para enxergar o "src.utils"
  correto. Este conftest troca os óculos automaticamente antes de cada arquivo.

Raciocinio: isola resolucao de imports entre suites para evitar conflito entre pacotes src homonimos.
"""

import sys
from pathlib import Path

# Caminho absoluto para a pasta test/ (onde este arquivo está)
_TEST_ROOT = Path(__file__).parent
# Caminho absoluto para a pasta app/ (onde os módulos do projeto estão)
_APP_ROOT = _TEST_ROOT.parent / "app"

# Mapeamento: nome da suite de testes → pasta do app correspondente.
# Ex: quando o pytest processa test/glue_agg/..., sabe que o app está em app/glue_agg/
_SUITE_TO_APP: dict[str, Path] = {
    "glue_agg": _APP_ROOT / "glue_agg",
    "glue_data_quality": _APP_ROOT / "glue_data_quality",
    "glue_etl": _APP_ROOT / "glue_etl",
    "glue_details": _APP_ROOT / "glue_details",
    "lambda_api": _APP_ROOT / "lambda_api",
}

# Mapeamento: nome da suite → nome completo do módulo utils no formato Python.
# Isso permite importar o módulo correto e registrá-lo como alias "src.utils".
# Suites sem entrada aqui não recebem alias src.utils (ex: lightsail usa estrutura diferente).
_SUITE_TO_SRC_MODULE: dict[str, str] = {
    "glue_agg": "app.glue_agg.src.utils",
    "glue_data_quality": "app.glue_data_quality.src.utils",
    "glue_etl": "app.glue_etl.src.utils",
    "glue_details": "app.glue_details.src.utils",
    "lambda_api": "app.lambda_api.src.utils",
}

# Conjuntos de todos os diretórios conhecidos de cada suite.
# Usados para "limpar" sys.path antes de adicionar a suite correta,
# evitando que diretórios de outras suites "contaminem" a suite atual.
_ALL_APP_DIRS: frozenset[str] = frozenset(str(p) for p in _SUITE_TO_APP.values())
_ALL_SRC_DIRS: frozenset[str] = frozenset(
    str(p / "src") for p in _SUITE_TO_APP.values()
)


def _set_suite_path(app_dir: Path) -> None:
    """
    Reconfigura sys.path para que apenas a suite atual seja visível.

    Coloca src/ e app_dir da suite no topo de sys.path, removendo todos os
    diretórios de outras suites que possam estar lá de execuções anteriores.

    Args:
        app_dir: Caminho para a pasta do app da suite ativa (ex: app/glue_etl/).
    """
    app_dir_str = str(app_dir)
    src_dir_str = str(app_dir / "src")
    # Reconstrói sys.path: src/ e app_dir da suite atual no início,
    # seguidos pelos outros caminhos que NÃO são de nenhuma suite conhecida.
    sys.path[:] = [src_dir_str, app_dir_str] + [
        p for p in sys.path if p not in _ALL_APP_DIRS and p not in _ALL_SRC_DIRS
    ]


def pytest_collect_file(parent, file_path):  # noqa: ARG001
    """
    Hook do pytest chamado antes de cada arquivo de teste ser importado.

    Aqui:
    1. Identifica qual suite o arquivo pertence (pelo nome da pasta)
    2. Remove os módulos src.* do cache Python (sys.modules)
    3. Reconfigura sys.path para a suite correta
    4. Importa o módulo de utils da suite e registra como alias "src.utils"

    Por que isso é necessário? Veja o docstring do módulo.
    """
    try:
        # Descobre o nome da suite: a primeira pasta após test/
        # Ex: test/glue_etl/test_main.py → suite = "glue_etl"
        suite = file_path.relative_to(_TEST_ROOT).parts[0]
    except (ValueError, IndexError):
        return

    app_dir = _SUITE_TO_APP.get(suite)
    if app_dir is None:
        return  # suite desconhecida (ex: lightsail, que tem estrutura diferente)

    # Remove do cache Python os módulos "src", "main", "utils" e "src.*"
    # para que a próxima importação use os módulos da suite correta.
    # Sem isso, Python reutilizaria o módulo em cache da suite anterior.
    for key in list(sys.modules.keys()):
        if key in ("src", "main", "utils") or key.startswith("src."):
            del sys.modules[key]

    # Reconfigura sys.path para a suite atual (remove diretórios de outras suites)
    _set_suite_path(app_dir)

    # Importa o módulo fully-qualified da suite (ex: app.glue_etl.src.utils)
    # e o registra como "src.utils" — alias que o código de produção usa.
    # Ex: em glue_etl/src/utils.py: "from src.utils import ..." resolve para
    #     app.glue_etl.src.utils após este alias ser estabelecido.
    fq_module = _SUITE_TO_SRC_MODULE.get(suite)
    if fq_module is None:
        return
    try:
        __import__(fq_module)
        mod = sys.modules[fq_module]
        sys.modules["src.utils"] = mod
        # Também expõe o pacote pai "src" para que imports como
        # "from src.rulesets_dq import ..." funcionem no glue_data_quality.
        src_pkg = fq_module.rsplit(".", 1)[0]  # ex: "app.glue_etl.src"
        if src_pkg in sys.modules:
            sys.modules["src"] = sys.modules[src_pkg]
            # Cria aliases para todos os submódulos de src (ex: src.rulesets_dq)
            prefix = src_pkg + "."
            for key in list(sys.modules.keys()):
                if key.startswith(prefix):
                    sys.modules["src." + key[len(prefix) :]] = sys.modules[key]
    except ImportError:
        pass


def _apply_suite_aliases(suite: str) -> None:
    """
    Reaplicar os aliases src.* para a suite correta antes de cada teste.

    Necessário porque o pytest pode mudar de arquivo (e de suite) entre testes,
    o que pode deixar os aliases apontando para a suite errada.
    """
    fq_module = _SUITE_TO_SRC_MODULE.get(suite)
    if not fq_module or fq_module not in sys.modules:
        return

    # Redefine src.utils para o módulo da suite atual
    sys.modules["src.utils"] = sys.modules[fq_module]
    src_pkg = fq_module.rsplit(".", 1)[0]  # ex: "app.glue_data_quality.src"
    if src_pkg in sys.modules:
        sys.modules["src"] = sys.modules[src_pkg]
        # Recria aliases para todos os submódulos
        prefix = src_pkg + "."
        for key in list(sys.modules.keys()):
            if key.startswith(prefix):
                sys.modules["src." + key[len(prefix) :]] = sys.modules[key]

    _set_suite_path(_SUITE_TO_APP[suite])


def pytest_runtest_setup(item):
    """
    Hook do pytest chamado imediatamente antes de cada teste ser executado.

    Garante que os aliases src.* estejam corretos para a suite do teste.
    Isso resolve o caso em que testes de suites diferentes são intercalados
    (ex: pytest coletar test/glue_etl/ e test/lambda_api/ e intercalar execução).
    """
    try:
        # Descobre a suite pelo caminho do arquivo do teste
        suite = item.path.relative_to(_TEST_ROOT).parts[0]
    except (ValueError, IndexError):
        return

    if suite in _SUITE_TO_SRC_MODULE:
        _apply_suite_aliases(suite)
