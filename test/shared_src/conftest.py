import sys
from pathlib import Path

_shared_dir = Path(__file__).parents[2] / "app" / "shared_src"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))
