from unittest.mock import patch

from langdetect import LangDetectException

from shared_utils.idioma_langdetect import detect_language_langdetect


class TestDetectLanguageLangdetect:
    def test_detecta_ingles(self):
        result = detect_language_langdetect("This is a clearly written English sentence with enough words.")
        assert result == "en"

    def test_detecta_portugues(self):
        result = detect_language_langdetect("Este é um texto claramente escrito em português, com bastante conteúdo.")
        assert result == "pt"

    def test_resultado_estavel_entre_chamadas_repetidas(self):
        """Regressão do seed fixo (DetectorFactory.seed = 0) — sem ele, langdetect usa
        amostragem probabilística e pode devolver idiomas diferentes entre chamadas
        para o mesmo texto."""
        text = "This is a clearly written English sentence with enough words."
        results = {detect_language_langdetect(text) for _ in range(5)}
        assert results == {"en"}

    def test_texto_vazio_devolve_none_sem_chamar_detect(self):
        with patch("shared_utils.idioma_langdetect.detect") as mock_detect:
            result = detect_language_langdetect("")
        assert result is None
        mock_detect.assert_not_called()

    def test_texto_so_espaco_devolve_none(self):
        assert detect_language_langdetect("   ") is None

    def test_lang_detect_exception_capturada(self):
        with patch(
            "shared_utils.idioma_langdetect.detect",
            side_effect=LangDetectException(0, "No features in text."),
        ):
            result = detect_language_langdetect("123 456")
        assert result is None

    def test_excecao_generica_capturada(self):
        with patch("shared_utils.idioma_langdetect.detect", side_effect=RuntimeError("boom")):
            result = detect_language_langdetect("some text")
        assert result is None
