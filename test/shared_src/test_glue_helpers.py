import logging
import sys
from unittest.mock import MagicMock, patch

from shared_utils.glue_helpers import configure_glue_logging, get_resolved_option


class TestGetResolvedOption:
    def test_delega_para_getResolvedOptions(self):
        mock_get = MagicMock(return_value={"FOO": "bar"})
        with patch("shared_utils.glue_helpers.getResolvedOptions", mock_get):
            result = get_resolved_option(["FOO"])
        mock_get.assert_called_once_with(sys.argv, ["FOO"])
        assert result == {"FOO": "bar"}

    def test_repassa_lista_vazia(self):
        mock_get = MagicMock(return_value={})
        with patch("shared_utils.glue_helpers.getResolvedOptions", mock_get):
            result = get_resolved_option([])
        mock_get.assert_called_once_with(sys.argv, [])
        assert result == {}

    def test_propaga_excecao_de_argumento_ausente(self):
        mock_get = MagicMock(side_effect=SystemExit(2))
        with patch("shared_utils.glue_helpers.getResolvedOptions", mock_get):
            try:
                get_resolved_option(["AUSENTE"])
            except SystemExit:
                pass
            else:
                raise AssertionError("SystemExit não foi propagada")


class TestConfigureGlueLogging:
    def test_retorna_logger(self):
        logger = configure_glue_logging()
        assert isinstance(logger, logging.Logger)

    def test_configura_nivel_info(self):
        configure_glue_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_handler_escreve_em_stdout(self):
        configure_glue_logging()
        root = logging.getLogger()
        handlers = root.handlers
        assert any(
            getattr(h, "stream", None) is sys.stdout
            for h in handlers
        )
