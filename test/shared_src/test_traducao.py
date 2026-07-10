from unittest.mock import MagicMock, patch

import pandas as pd

from shared_utils.traducao import (
    elegivel_keywords_pt,
    elegivel_overview_pt,
    elegivel_tagline_pt,
    traduzir_em_paralelo,
    traduzir_texto,
)


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

    def test_tenta_novamente_quando_resultado_identico_ao_original(self):
        """Sem exceção, mas resultado igual ao original: conta como tentativa falha."""
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = ["Hello", "Olá"]
        with (
            patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao.time.sleep") as mock_sleep,
        ):
            result = traduzir_texto("Hello")
        assert result == "Olá"
        assert mock_translator.translate.call_count == 2
        mock_sleep.assert_called_once_with(2)

    def test_desiste_cedo_quando_sempre_identico_sem_excecao(self):
        """Nenhuma exceção é lançada em nenhuma tentativa, mas o texto nunca muda —
        isso costuma indicar que não há o que traduzir (nome próprio, termo
        emprestado), não bloqueio transitório, então desiste em
        _MAX_TENTATIVAS_SEM_ERRO tentativas (2), não nas 5 completas."""
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "Hello"
        with (
            patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao.time.sleep"),
        ):
            result = traduzir_texto("Hello")
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
            patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao.time.sleep"),
        ):
            with caplog.at_level(logging.DEBUG):
                traduzir_texto("Hello")
        assert "não há tradução a fazer" in caplog.text

    def test_contador_de_resultado_identico_nao_precisa_ser_consecutivo(self):
        """O limite de _MAX_TENTATIVAS_SEM_ERRO soma tentativas sem erro e resultado
        idêntico ao total (mesmo com uma exceção intercalada), não exige que sejam
        consecutivas."""
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = ["Hello", Exception("timeout"), "Hello"]
        with (
            patch("shared_utils.traducao.GoogleTranslator", return_value=mock_translator),
            patch("shared_utils.traducao.time.sleep"),
        ):
            result = traduzir_texto("Hello")
        assert result == "Hello"
        assert mock_translator.translate.call_count == 3

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
        mock_cls.assert_called_once_with(source="auto", target="pt")


class TestTraduzirEmParalelo:
    def test_traduz_cada_valor_e_preserva_a_ordem(self):
        traduzir_fn = MagicMock(side_effect=lambda t: f"[PT] {t}")
        resultado = traduzir_em_paralelo(["Hello", "World"], traduzir_fn)
        assert resultado == ["[PT] Hello", "[PT] World"]

    def test_lista_vazia_nao_chama_traduzir_fn(self):
        traduzir_fn = MagicMock()
        assert traduzir_em_paralelo([], traduzir_fn) == []
        traduzir_fn.assert_not_called()

    def test_usa_max_workers_informado(self):
        """max_workers é repassado ao ThreadPoolExecutor, não hardcoded."""
        with patch("shared_utils.traducao.ThreadPoolExecutor") as mock_executor_cls:
            mock_executor = mock_executor_cls.return_value.__enter__.return_value
            mock_executor.map.return_value = iter(["ok"])
            traduzir_em_paralelo(["Hello"], MagicMock(), max_workers=3)
        mock_executor_cls.assert_called_once_with(max_workers=3)


class TestElegivelOverviewPt:
    def test_elegivel_quando_en_e_overview_preenchido(self):
        df = pd.DataFrame({"original_language": ["en"], "overview_en": ["Hello"]})
        assert elegivel_overview_pt(df).tolist() == [True]

    def test_nao_elegivel_quando_idioma_nao_e_en(self):
        df = pd.DataFrame({"original_language": ["fr"], "overview_en": ["Bonjour"]})
        assert elegivel_overview_pt(df).tolist() == [False]

    def test_nao_elegivel_quando_overview_en_vazio_ou_nulo(self):
        df = pd.DataFrame({"original_language": ["en", "en"], "overview_en": ["", None]})
        assert elegivel_overview_pt(df).tolist() == [False, False]


class TestElegivelTaglinePt:
    def test_elegivel_para_qualquer_idioma_com_tagline_preenchida(self):
        df = pd.DataFrame({"tagline": ["Slogan A", "Slogan B"]})
        assert elegivel_tagline_pt(df).tolist() == [True, True]

    def test_nao_elegivel_quando_tagline_vazia_ou_nula(self):
        df = pd.DataFrame({"tagline": ["", None]})
        assert elegivel_tagline_pt(df).tolist() == [False, False]


class TestElegivelKeywordsPt:
    def test_elegivel_para_qualquer_idioma_com_keywords_preenchidas(self):
        df = pd.DataFrame({"keywords": ["action, drama"]})
        assert elegivel_keywords_pt(df).tolist() == [True]

    def test_nao_elegivel_quando_keywords_vazias_ou_nulas(self):
        df = pd.DataFrame({"keywords": ["", None]})
        assert elegivel_keywords_pt(df).tolist() == [False, False]
