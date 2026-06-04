import os
import sys

import pytest

_RECOMMENDER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../app/lambda_recommender")
)
_API_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../app/lambda_api")
)

_SHARED_NAMES = {"main", "src"}


@pytest.fixture(autouse=True)
def _use_recommender_modules():
    old_path = sys.path[:]
    old_modules = {k: v for k, v in sys.modules.items()
                   if k in _SHARED_NAMES or k.startswith("src.")}

    if _API_PATH in sys.path:
        sys.path.remove(_API_PATH)
    sys.path.insert(0, _RECOMMENDER_PATH)

    for mod in old_modules:
        sys.modules.pop(mod, None)

    yield

    sys.path[:] = old_path
    for mod in list(sys.modules.keys()):
        if mod in _SHARED_NAMES or mod.startswith("src."):
            sys.modules.pop(mod, None)
    sys.modules.update(old_modules)
