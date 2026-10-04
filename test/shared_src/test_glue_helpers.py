import logging
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
from shared_utils.glue_helpers import (
    add_processed_date,
    configure_glue_logging,
    current_processed_date,
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


class TestCurrentProcessedDate:
    def test_retorna_objeto_date_sem_hora(self):
        valor = current_processed_date()
        assert type(valor) is date

    def test_usa_data_local_de_sao_paulo_e_nao_utc(self):
        # 02:30 UTC de 05/10 ainda é 23:30 de 04/10 em São Paulo (UTC-3).
        fixed = pd.Timestamp("2026-10-05 02:30:00", tz="UTC").tz_convert("America/Sao_Paulo")
        with patch("shared_utils.glue_helpers.pd.Timestamp.now", return_value=fixed) as mock_now:
            valor = current_processed_date()
        mock_now.assert_called_once_with(tz="America/Sao_Paulo")
        assert valor == date(2026, 10, 4)


class TestAddProcessedDate:
    def test_adiciona_coluna_como_ultima(self):
        df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        result = add_processed_date(df)
        assert list(result.columns) == ["id", "name", "processed_date"]

    def test_muta_o_proprio_dataframe(self):
        df = pd.DataFrame({"id": [1]})
        result = add_processed_date(df)
        assert result is df
        assert "processed_date" in df.columns

    def test_valor_unico_do_tipo_date(self):
        df = pd.DataFrame({"id": [1, 2, 3]})
        add_processed_date(df)
        assert all(type(v) is date for v in df["processed_date"])
        assert df["processed_date"].nunique() == 1

    def test_usa_current_processed_date(self):
        df = pd.DataFrame({"id": [1]})
        with patch("shared_utils.glue_helpers.current_processed_date", return_value=date(2026, 10, 4)):
            add_processed_date(df)
        assert df["processed_date"].iloc[0] == date(2026, 10, 4)

    def test_sobrescreve_coluna_existente(self):
        df = pd.DataFrame({"processed_date": [date(2000, 1, 1)], "id": [1]})
        add_processed_date(df)
        assert df["processed_date"].iloc[0] > date(2020, 1, 1)
