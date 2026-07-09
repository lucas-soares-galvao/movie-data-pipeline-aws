from unittest.mock import MagicMock, patch

from shared_utils.traducao import traduzir_texto


class TestTraduzirTexto:
    def test_retorna_string_vazia_para_entrada_vazia(self):
        assert traduzir_texto("") == ""

    def test_retorna_string_vazia_para_none(self):
        assert traduzir_texto(None) == ""

    def test_traduz_texto_com_sucesso(self):
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Olá"
        with patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator):
            result = traduzir_texto("Hello")
        assert result == "Olá"
        mock_translator.translate.assert_called_once_with("Hello")

    def test_retorna_original_apos_esgotar_tentativas(self):
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("rate limit")
        with (
            patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao.time.sleep"),
        ):
            result = traduzir_texto("Hello")
        assert result == "Hello"
        assert mock_translator.translate.call_count == 5

    def test_tenta_novamente_apos_excecao_e_depois_sucede(self):
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = [Exception("timeout"), "Olá"]
        with (
            patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao.time.sleep") as mock_sleep,
        ):
            result = traduzir_texto("Hello")
        assert result == "Olá"
        assert mock_translator.translate.call_count == 2
        mock_sleep.assert_called_once_with(2)

    def test_log_warning_em_caso_de_excecao(self, caplog):
        import logging
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("timeout")
        with (
            patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao.time.sleep"),
        ):
            with caplog.at_level(logging.WARNING):
                traduzir_texto("Hello")
        assert "Falha ao traduzir" in caplog.text

    def test_contexto_aparece_no_log(self, caplog):
        import logging
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("err")
        with (
            patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao.time.sleep"),
        ):
            with caplog.at_level(logging.WARNING):
                traduzir_texto("Hello", contexto="países")
        assert "países" in caplog.text

    def test_cria_translator_com_idiomas_corretos(self):
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "ok"
        with patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator) as mock_cls:
            traduzir_texto("test")
        mock_cls.assert_called_once_with(source="en", target="pt")
