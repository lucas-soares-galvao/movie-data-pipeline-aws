import logging
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
from shared_utils.glue_helpers import (
    add_processing_datetime,
    configure_glue_logging,
    get_resolved_option,
)


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


class TestAddProcessingDatetime:
    def test_adiciona_coluna_como_ultima(self):
        df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        result = add_processing_datetime(df)
        assert list(result.columns) == ["id", "name", "processing_datetime"]

    def test_muta_o_proprio_dataframe(self):
        df = pd.DataFrame({"id": [1]})
        result = add_processing_datetime(df)
        assert result is df
        assert "processing_datetime" in df.columns

    def test_valor_unico_timestamp_sem_fuso(self):
        df = pd.DataFrame({"id": [1, 2, 3]})
        add_processing_datetime(df)
        col = df["processing_datetime"]
        assert pd.api.types.is_datetime64_dtype(col)
        assert col.dt.tz is None
        assert col.nunique() == 1

    def test_usa_hora_local_de_sao_paulo(self):
        fixed = pd.Timestamp("2026-10-04 15:30:00", tz="America/Sao_Paulo")
        df = pd.DataFrame({"id": [1]})
        with patch("shared_utils.glue_helpers.pd.Timestamp.now", return_value=fixed) as mock_now:
            add_processing_datetime(df)
        mock_now.assert_called_once_with(tz="America/Sao_Paulo")
        assert df["processing_datetime"].iloc[0] == pd.Timestamp("2026-10-04 15:30:00")

    def test_sobrescreve_coluna_existente(self):
        df = pd.DataFrame({"processing_datetime": [pd.Timestamp("2000-01-01")], "id": [1]})
        add_processing_datetime(df)
        assert df["processing_datetime"].iloc[0] > pd.Timestamp("2020-01-01")
