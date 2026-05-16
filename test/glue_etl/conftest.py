import sys
import os
from unittest.mock import MagicMock

# Allows Glue job modules to resolve 'src.utils' as in the AWS Glue runtime.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app", "glue_etl"))

# Mock AWS Glue libraries unavailable outside the Glue runtime.
sys.modules.setdefault("awsglue", MagicMock())
sys.modules.setdefault("awsglue.utils", MagicMock())
