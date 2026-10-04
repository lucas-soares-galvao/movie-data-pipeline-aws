import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import litellm
from shared_utils import llm_metrics, traducao_llm
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


class TestLoggingDoLiteLLM:
    def test_logger_do_litellm_so_emite_warning_ou_acima(self):
        """O LiteLLM loga 2 linhas INFO por chamada; milhares de chamadas afogavam o log do
        backfill. WARNING/ERROR (falhas reais) continuam passando."""
        assert logging.getLogger("LiteLLM").level == logging.WARNING
        assert litellm.suppress_debug_info is True


class TestGetLlmApiKey:
    def test_le_o_secret_uma_unica_vez_sob_concorrencia(self, monkeypatch):
        """A tradução/detecção roda em ThreadPoolExecutor: sem o lock, várias threads vendo o
        cache vazio ao mesmo tempo leriam o Secrets Manager uma vez cada."""
        monkeypatch.setattr(traducao_llm, "_llm_api_key_cache", [])
        chamadas = []

        def carregar_lenta(*args, **kwargs):
            chamadas.append(1)
            time.sleep(0.05)
            return "chave"

        monkeypatch.setattr(traducao_llm, "load_llm_api_key", carregar_lenta)
        resultados = []
        threads = [
            threading.Thread(target=lambda: resultados.append(traducao_llm._get_llm_api_key()))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(chamadas) == 1
        assert resultados == ["chave"] * 8


def _resposta_com_uso(content, model="qwen/qwen3.8-flash"):
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, cost=0.0004),
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


class TestRegistroDeMetricasNaTraducao:
    """Cada chamada de translate_text_llm é registrada em llm_metrics, sem mudar o retorno."""

    def test_sucesso_registra_ok_com_modelo_tokens_e_custo(self):
        with llm_metrics.llm_usage_scope() as usage:
            with patch("shared_utils.traducao_llm.litellm.completion", return_value=_resposta_com_uso("Olá")):
                assert translate_text_llm("Hello") == "Olá"
        assert usage.outcomes == {llm_metrics.OK: 1}
        assert usage.calls_by_operation == {"tradução": 1}
        assert usage.models == {"qwen/qwen3.8-flash": 1}
        assert (usage.prompt_tokens, usage.completion_tokens) == (12, 3)
        assert usage.cost == 0.0004

    def test_resultado_igual_ao_original_registra_sem_mudanca(self):
        with llm_metrics.llm_usage_scope() as usage:
            with patch("shared_utils.traducao_llm.litellm.completion", return_value=_resposta_com_uso("softcore")):
                assert translate_text_llm("softcore") == "softcore"
        assert usage.outcomes == {llm_metrics.NO_CHANGE: 1}
        assert usage.failures == {}

    def test_resposta_vazia_registra_falha_vazia(self):
        with llm_metrics.llm_usage_scope() as usage:
            with patch("shared_utils.traducao_llm.litellm.completion", return_value=_resposta_com_uso("  ")):
                assert translate_text_llm("Hello") == "Hello"
        assert usage.failures == {llm_metrics.EMPTY: 1}

    def test_excecao_registra_a_causa_pelo_nome_da_classe(self):
        with llm_metrics.llm_usage_scope() as usage:
            with patch(
                "shared_utils.traducao_llm.litellm.completion",
                side_effect=ImportError("tenacity import failed"),
            ):
                assert translate_text_llm("Hello") == "Hello"
        assert usage.failures == {"ImportError": 1}
        assert "tenacity import failed" in usage.samples["ImportError"][0]
