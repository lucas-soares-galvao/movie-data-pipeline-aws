import logging
import sys
from unittest.mock import MagicMock, patch

from shared_utils.glue_helpers import configure_glue_logging, get_resolved_option


class TestGetResolvedOption:
    def test_delega_para_getResolvedOptions(self):
        mock_get = MagicMock(return_value={"FOO": "bar"})
        with patch("awsglue.utils.getResolvedOptions", mock_get):
            result = get_resolved_option(["FOO"])
        mock_get.assert_called_once_with(sys.argv, ["FOO"])
        assert result == {"FOO": "bar"}

    def test_repassa_lista_vazia(self):
        mock_get = MagicMock(return_value={})
        with patch("awsglue.utils.getResolvedOptions", mock_get):
            result = get_resolved_option([])
        mock_get.assert_called_once_with(sys.argv, [])
        assert result == {}

    def test_propaga_excecao_de_argumento_ausente(self):
        mock_get = MagicMock(side_effect=SystemExit(2))
        with patch("awsglue.utils.getResolvedOptions", mock_get):
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

    def test_mascara_segredos_no_que_e_logado(self, capsys):
        """Um log de exceção do requests embute a URL com a api_key: nunca deve chegar ao CloudWatch."""
        configure_glue_logging()
        logging.getLogger().warning(
            "Falha ao buscar coleção 1: 404 for url: https://api.themoviedb.org/3/collection/1"
            "?api_key=0123456789abcdef0123456789abcdef&language=pt-BR"
        )
        saida = capsys.readouterr().out
        assert "0123456789abcdef0123456789abcdef" not in saida
        assert "api_key=***&language=pt-BR" in saida
