"""Mocks para módulos ausentes no ambiente de teste (streamlit)."""

import sys
from unittest.mock import MagicMock

_st_mock = MagicMock()
_st_mock.button.return_value = False
_st_mock.text_input.return_value = ""

sys.modules.setdefault("streamlit", _st_mock)
