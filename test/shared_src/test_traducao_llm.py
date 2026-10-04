from unittest.mock import MagicMock, patch

from shared_utils.traducao_llm import translate_text_llm


def _mock_response(content: str | None) -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


class TestTranslateTextLlm:
    def test_texto_vazio_nao_chama_api(self):
        with patch("shared_utils.traducao_llm.litellm.completion") as mock_completion:
            assert translate_text_llm("") == ""
        mock_completion.assert_not_called()

    def test_none_nao_chama_api(self):
        with patch("shared_utils.traducao_llm.litellm.completion") as mock_completion:
            assert translate_text_llm(None) == ""
        mock_completion.assert_not_called()

    def test_traduz_com_sucesso(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response("Olá")):
            assert translate_text_llm("Hello") == "Olá"

    def test_excecao_na_chamada_devolve_original(self):
        with patch("shared_utils.traducao_llm.litellm.completion", side_effect=Exception("timeout")):
            assert translate_text_llm("Hello") == "Hello"

    def test_content_vazio_devolve_original(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response("")):
            assert translate_text_llm("Hello") == "Hello"

    def test_content_none_devolve_original(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response(None)):
            assert translate_text_llm("Hello") == "Hello"

    def test_content_so_espacos_devolve_original(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response("   ")):
            assert translate_text_llm("Hello") == "Hello"

    def test_resultado_igual_ao_original_e_devolvido_mesmo_assim(self):
        """Nome próprio/termo sem tradução — o LLM pode ecoar o texto original de
        propósito; resolve_pt_translation decide o que fazer com isso via comparação,
        não translate_text_llm."""
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response("Iron Man")):
            assert translate_text_llm("Iron Man") == "Iron Man"

    def test_remove_aspas_ao_redor_do_resultado(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response('"Olá"')):
            assert translate_text_llm("Hello") == "Olá"

    def test_remove_cerca_de_markdown_ao_redor_do_resultado(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response("```\nOlá\n```")):
            assert translate_text_llm("Hello") == "Olá"

    def test_passa_modelo_e_chave_configurados(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response("Olá")) as mock_completion:
            translate_text_llm("Hello")
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "openrouter/qwen/qwen3.8-flash"
        assert kwargs["temperature"] == 0

    def test_repassa_fallback_de_modelo_no_extra_body(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response("Olá")) as mock_completion:
            translate_text_llm("Hello")
        extra_body = mock_completion.call_args.kwargs["extra_body"]
        assert extra_body["models"] == ["deepseek/deepseek-v4.1-flash"]
        assert extra_body["reasoning"] == {"enabled": False}

    def test_mensagem_do_usuario_e_o_proprio_texto(self):
        with patch("shared_utils.traducao_llm.litellm.completion", return_value=_mock_response("Olá")) as mock_completion:
            translate_text_llm("Hello")
        messages = mock_completion.call_args.kwargs["messages"]
        assert messages[-1] == {"role": "user", "content": "Hello"}
        assert messages[0]["role"] == "system"
