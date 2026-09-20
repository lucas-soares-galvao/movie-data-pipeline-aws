import logging
from unittest.mock import MagicMock, patch

import pytest
from shared_utils.traducao_google import is_google_error_page, translate_text

# Texto real observado nas tabelas do dev (name_pt/overview_pt) no lugar da tradução.
GOOGLE_ERROR_PAGE = (
    "Error 500 (Server Error)!!1500.That’s an error.There was an error. "
    "Please try again later.That’s all we know."
)


class TestIsGoogleErrorPage:
    def test_casa_o_texto_de_erro_real_observado(self):
        assert is_google_error_page(GOOGLE_ERROR_PAGE) is True

    def test_casa_outro_status_http(self):
        assert is_google_error_page("Error 404 (Not Found)!!1404.That’s an error.") is True

    @pytest.mark.parametrize("texto", ["Olá", "Japonês", "", "Error", "Error 500", "Erro 500 (Server Error)!!1"])
    def test_nao_casa_traducao_normal_nem_prefixo_incompleto(self, texto):
        assert is_google_error_page(texto) is False

    def test_nao_casa_quando_erro_aparece_so_no_meio_do_texto(self):
        assert is_google_error_page("Mensagem: Error 500 (Server Error)!!1 no meio") is False

    @pytest.mark.parametrize("valor", [None, float("nan"), 123, ["Error 500 (Server Error)!!1"]])
    def test_nao_string_devolve_false(self, valor):
        """O valor vem de colunas de DataFrame, onde pode ser None/NaN."""
        assert is_google_error_page(valor) is False


class TestTranslateTextPaginaDeErro:
    def test_trata_pagina_de_erro_como_falha_e_tenta_de_novo(self):
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = [GOOGLE_ERROR_PAGE, "Olá"]
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep") as mock_sleep,
        ):
            result = translate_text("Hello")
        assert result == "Olá"
        assert mock_translator.translate.call_count == 2
        mock_sleep.assert_called_once_with(2)

    def test_devolve_original_apos_esgotar_tentativas_com_pagina_de_erro(self):
        """Usa o orçamento completo de tentativas (como uma exceção), não desiste cedo
        como no caso de texto idêntico — página de erro é bloqueio, não 'nada a traduzir'."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = GOOGLE_ERROR_PAGE
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            result = translate_text("Japanese")
        assert result == "Japanese"
        assert mock_translator.translate.call_count == 5

    def test_loga_warning_quando_esgota_tentativas_com_pagina_de_erro(self, caplog):
        """WARNING (não DEBUG): é o único sinal visível de bloqueio real do Google."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = GOOGLE_ERROR_PAGE
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            with caplog.at_level(logging.WARNING):
                translate_text("Japanese", context="idiomas")
        assert "página de erro" in caplog.text
        assert "Error 500" in caplog.text
        assert "idiomas" in caplog.text

    def test_nao_loga_warning_quando_a_falha_e_so_excecao(self, caplog):
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("timeout")
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            with caplog.at_level(logging.WARNING):
                translate_text("Hello")
        assert "página de erro" not in caplog.text

    def test_nao_rejeita_quando_o_proprio_texto_de_entrada_e_pagina_de_erro(self):
        """Sem essa exceção, um texto de entrada que já é a página de erro nunca poderia
        ser devolvido pelo tradutor, e cada chamada gastaria as 5 tentativas em vão."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Erro 500 (Erro do servidor)"
        with patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator):
            result = translate_text(GOOGLE_ERROR_PAGE)
        assert result == "Erro 500 (Erro do servidor)"
        assert mock_translator.translate.call_count == 1

    def test_pagina_de_erro_nao_conta_como_resultado_identico(self):
        """A página de erro não entra em attempts_no_error: só os 2 resultados idênticos
        seguintes fecham o limite de _MAX_ATTEMPTS_NO_ERROR (3 chamadas no total)."""
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = [GOOGLE_ERROR_PAGE, "Hello", "Hello"]
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            result = translate_text("Hello")
        assert result == "Hello"
        assert mock_translator.translate.call_count == 3


class TestTranslateText:
    def test_retorna_string_vazia_para_entrada_vazia(self):
        assert translate_text("") == ""

    def test_retorna_string_vazia_para_none(self):
        assert translate_text(None) == ""

    def test_traduz_texto_com_sucesso(self):
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Olá"
        with patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator):
            result = translate_text("Hello")
        assert result == "Olá"
        mock_translator.translate.assert_called_once_with("Hello")

    def test_retorna_original_apos_esgotar_tentativas(self):
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("rate limit")
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            result = translate_text("Hello")
        assert result == "Hello"
        assert mock_translator.translate.call_count == 5

    def test_tenta_novamente_apos_excecao_e_depois_sucede(self):
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = [Exception("timeout"), "Olá"]
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep") as mock_sleep,
        ):
            result = translate_text("Hello")
        assert result == "Olá"
        assert mock_translator.translate.call_count == 2
        mock_sleep.assert_called_once_with(2)

    def test_tenta_novamente_quando_resultado_identico_ao_original(self):
        """Sem exceção, mas resultado igual ao original: conta como tentativa falha."""
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = ["Hello", "Olá"]
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep") as mock_sleep,
        ):
            result = translate_text("Hello")
        assert result == "Olá"
        assert mock_translator.translate.call_count == 2
        mock_sleep.assert_called_once_with(2)

    def test_desiste_cedo_quando_sempre_identico_sem_excecao(self):
        """Nenhuma exceção é lançada em nenhuma tentativa, mas o texto nunca muda —
        isso costuma indicar que não há o que traduzir (nome próprio, termo
        emprestado), não bloqueio transitório, então desiste em
        _MAX_ATTEMPTS_NO_ERROR tentativas (2), não nas 5 completas."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Hello"
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            result = translate_text("Hello")
        assert result == "Hello"
        assert mock_translator.translate.call_count == 2

    def test_log_debug_quando_desiste_cedo_por_resultado_identico(self, caplog):
        """Nível DEBUG (não INFO): esse desfecho é comum (nomes próprios, termos
        emprestados) e não deve poluir o log padrão do workflow com uma linha por
        registro — só o resumo por coluna aparece em INFO."""
        import logging
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Hello"
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            with caplog.at_level(logging.DEBUG):
                translate_text("Hello")
        assert "não há tradução a fazer" in caplog.text

    def test_contador_de_resultado_identico_nao_precisa_ser_consecutivo(self):
        """O limite de _MAX_ATTEMPTS_NO_ERROR soma tentativas sem erro e resultado
        idêntico ao total (mesmo com uma exceção intercalada), não exige que sejam
        consecutivas."""
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = ["Hello", Exception("timeout"), "Hello"]
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            result = translate_text("Hello")
        assert result == "Hello"
        assert mock_translator.translate.call_count == 3

    def test_log_debug_em_caso_de_excecao(self, caplog):
        """Nível DEBUG (não WARNING): esgotar tentativas por erro é comum sob
        alto volume (rate-limit do endpoint não-oficial) e não deve poluir o log
        padrão do workflow com uma linha por registro — só o resumo agregado de
        falhas/elegíveis, logado em resolve_pt_translation, aparece em INFO."""
        import logging
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("timeout")
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            with caplog.at_level(logging.DEBUG):
                translate_text("Hello")
        assert "Falha ao traduzir" in caplog.text

    def test_contexto_aparece_no_log(self, caplog):
        import logging
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("err")
        with (
            patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao_google.time.sleep"),
        ):
            with caplog.at_level(logging.DEBUG):
                translate_text("Hello", context="países")
        assert "países" in caplog.text

    def test_cria_translator_com_idiomas_corretos(self):
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "ok"
        with patch("shared_utils.traducao_google.GoogleTranslator", return_value=mock_translator) as mock_cls:
            translate_text("test")
        mock_cls.assert_called_once_with(source="auto", target="pt")
