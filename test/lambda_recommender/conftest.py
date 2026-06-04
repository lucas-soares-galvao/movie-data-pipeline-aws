import os
import sys

_RECOMMENDER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../app/lambda_recommender")
)
if _RECOMMENDER_PATH not in sys.path:
    sys.path.insert(0, _RECOMMENDER_PATH)

# Clear cached modules from lambda_api that share the same bare names
for _mod in list(sys.modules.keys()):
    if _mod in ("main", "src") or _mod.startswith("src."):
        del sys.modules[_mod]
