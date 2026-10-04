from unittest.mock import MagicMock, patch

from shared_utils.idioma_llm import detect_language_llm


def _mock_response(content: str | None) -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


class TestDetectLanguageLlm:
    def test_texto_vazio_devolve_none_sem_chamar_api(self):
        with patch("shared_utils.idioma_llm.litellm.completion") as mock_completion:
            assert detect_language_llm("") is None
        mock_completion.assert_not_called()

    def test_texto_so_espacos_devolve_none_sem_chamar_api(self):
        with patch("shared_utils.idioma_llm.litellm.completion") as mock_completion:
            assert detect_language_llm("   ") is None
        mock_completion.assert_not_called()

    def test_detecta_com_sucesso(self):
        with patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response("en")):
            assert detect_language_llm("Hello") == "en"

    def test_normaliza_maiusculas(self):
        with patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response("EN")):
            assert detect_language_llm("Hello") == "en"

    def test_remove_espacos_ao_redor_do_codigo(self):
        with patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response(" pt ")):
            assert detect_language_llm("Olá") == "pt"

    def test_excecao_na_chamada_devolve_none(self):
        with patch("shared_utils.idioma_llm.litellm.completion", side_effect=Exception("timeout")):
            assert detect_language_llm("Hello") is None

    def test_content_none_devolve_none(self):
        with patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response(None)):
            assert detect_language_llm("Hello") is None

    def test_codigo_fora_do_padrao_iso_639_1_devolve_none(self):
        """Resposta fora do formato esperado (frase, 3+ letras) nunca é propagada —
        evitaria poluir detected_language_*_column com um valor inválido."""
        with patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response("inglês")):
            assert detect_language_llm("Hello") is None

    def test_codigo_com_numero_devolve_none(self):
        with patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response("e1")):
            assert detect_language_llm("Hello") is None

    def test_loga_warning_para_codigo_fora_do_padrao(self, caplog):
        import logging
        with (
            patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response("não sei")),
            caplog.at_level(logging.WARNING),
        ):
            detect_language_llm("Hello")
        assert "fora do padrão ISO 639-1" in caplog.text

    def test_passa_modelo_e_chave_configurados(self):
        with patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response("en")) as mock_completion:
            detect_language_llm("Hello")
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "openrouter/qwen/qwen3.8-flash"
        assert kwargs["temperature"] == 0

    def test_repassa_fallback_de_modelo_no_extra_body(self):
        with patch("shared_utils.idioma_llm.litellm.completion", return_value=_mock_response("en")) as mock_completion:
            detect_language_llm("Hello")
        extra_body = mock_completion.call_args.kwargs["extra_body"]
        assert extra_body["models"] == ["deepseek/deepseek-v4.1-flash"]
