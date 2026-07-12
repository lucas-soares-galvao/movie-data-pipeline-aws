from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pandas as pd

import shared_utils.traducao as traducao
from shared_utils.traducao import (
    criar_traduzir_fn_com_aws_translate,
    elegivel_keywords_pt,
    elegivel_overview_pt,
    elegivel_tagline_pt,
    traduzir_coluna_pendente,
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


class TestTraduzirColunaPendente:
    def test_traduz_registros_elegiveis_pendentes(self):
        df = pd.DataFrame({"fonte": ["Hello", "World"], "destino": [None, None]})
        traduzir_fn = MagicMock(side_effect=lambda t: f"[PT] {t}")
        mask = pd.Series([True, True])

        sucesso = traduzir_coluna_pendente(df, "fonte", "destino", mask, traduzir_fn)

        assert sucesso == 2
        assert df["destino"].tolist() == ["[PT] Hello", "[PT] World"]

    def test_cria_coluna_destino_se_nao_existir(self):
        df = pd.DataFrame({"fonte": ["Hello"]})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        traduzir_coluna_pendente(df, "fonte", "destino", pd.Series([True]), traduzir_fn)

        assert df["destino"].tolist() == ["Olá"]

    def test_pula_registro_ja_traduzido_com_sucesso(self):
        """destino preenchido e diferente da fonte: não é retraduzido."""
        df = pd.DataFrame({"fonte": ["Hello"], "destino": ["Olá"]})
        traduzir_fn = MagicMock()

        sucesso = traduzir_coluna_pendente(df, "fonte", "destino", pd.Series([True]), traduzir_fn)

        assert sucesso == 0
        assert df["destino"].tolist() == ["Olá"]
        traduzir_fn.assert_not_called()

    def test_retenta_quando_destino_igual_a_fonte(self):
        """destino == fonte indica fallback de uma tradução que falhou em um run
        anterior (ver traduzir_texto) — deve ser retentado, não pulado."""
        df = pd.DataFrame({"fonte": ["Hello"], "destino": ["Hello"]})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        sucesso = traduzir_coluna_pendente(df, "fonte", "destino", pd.Series([True]), traduzir_fn)

        assert sucesso == 1
        assert df["destino"].tolist() == ["Olá"]

    def test_nao_elegivel_nao_e_traduzido(self):
        df = pd.DataFrame({"fonte": ["Hello"], "destino": [None]})
        traduzir_fn = MagicMock()

        sucesso = traduzir_coluna_pendente(df, "fonte", "destino", pd.Series([False]), traduzir_fn)

        assert sucesso == 0
        traduzir_fn.assert_not_called()

    def test_mask_vazia_nao_chama_traduzir_fn(self):
        df = pd.DataFrame({"fonte": [], "destino": []})
        traduzir_fn = MagicMock()

        sucesso = traduzir_coluna_pendente(df, "fonte", "destino", pd.Series([], dtype=bool), traduzir_fn)

        assert sucesso == 0
        traduzir_fn.assert_not_called()

    def test_sucesso_nao_conta_quando_traducao_falha_e_mantem_original(self):
        """traduzir_fn pode devolver o próprio texto original em caso de falha
        (ver traduzir_texto); esses casos não contam como sucesso."""
        df = pd.DataFrame({"fonte": ["Hello", "World"], "destino": [None, None]})
        traduzir_fn = MagicMock(side_effect=lambda t: t if t == "Hello" else f"[PT] {t}")

        sucesso = traduzir_coluna_pendente(df, "fonte", "destino", pd.Series([True, True]), traduzir_fn)

        assert sucesso == 1
        assert df["destino"].tolist() == ["Hello", "[PT] World"]

    def test_usa_max_workers_informado(self):
        with patch("shared_utils.traducao.traduzir_em_paralelo") as mock_paralelo:
            mock_paralelo.return_value = ["Olá"]
            df = pd.DataFrame({"fonte": ["Hello"], "destino": [None]})
            traduzir_coluna_pendente(df, "fonte", "destino", pd.Series([True]), MagicMock(), max_workers=3)
        assert mock_paralelo.call_args.kwargs["max_workers"] == 3


class TestTraduzirAwsTranslate:
    def test_traduz_com_sucesso(self):
        mock_client = MagicMock()
        mock_client.translate_text.return_value = {"TranslatedText": "Olá"}
        with patch("shared_utils.traducao.boto3.client", return_value=mock_client) as mock_boto:
            result = traducao._traduzir_aws_translate("Hello", region="sa-east-1")
        assert result == "Olá"
        mock_boto.assert_called_once_with("translate", region_name="sa-east-1")
        mock_client.translate_text.assert_called_once_with(
            Text="Hello", SourceLanguageCode="auto", TargetLanguageCode="pt",
        )

    def test_retorna_original_em_caso_de_excecao(self):
        with patch("shared_utils.traducao.boto3.client", side_effect=Exception("boom")):
            result = traducao._traduzir_aws_translate("Hello", region="sa-east-1")
        assert result == "Hello"

    def test_retorna_original_quando_resposta_vazia(self):
        mock_client = MagicMock()
        mock_client.translate_text.return_value = {"TranslatedText": ""}
        with patch("shared_utils.traducao.boto3.client", return_value=mock_client):
            result = traducao._traduzir_aws_translate("Hello", region="sa-east-1")
        assert result == "Hello"


class TestCriarTraduzirFnComAwsTranslate:
    def test_nao_chama_aws_translate_quando_traducao_primaria_tem_sucesso(self):
        traduzir_fn_primario = MagicMock(return_value="Olá")
        with patch("shared_utils.traducao._traduzir_aws_translate") as mock_aws:
            fn = criar_traduzir_fn_com_aws_translate(traduzir_fn_primario, max_chamadas=5)
            result = fn("Hello")
        assert result == "Olá"
        mock_aws.assert_not_called()

    def test_chama_aws_translate_quando_traducao_primaria_falha(self):
        """traduzir_fn_primario devolve o texto original quando falha (mesmo contrato
        de traduzir_texto) — é esse sinal que aciona o fallback."""
        traduzir_fn_primario = MagicMock(return_value="Hello")
        with patch("shared_utils.traducao._traduzir_aws_translate", return_value="Olá via AWS") as mock_aws:
            fn = criar_traduzir_fn_com_aws_translate(traduzir_fn_primario, max_chamadas=5)
            result = fn("Hello")
        assert result == "Olá via AWS"
        mock_aws.assert_called_once_with("Hello", "sa-east-1")

    def test_nao_chama_nada_para_texto_vazio(self):
        traduzir_fn_primario = MagicMock(return_value="")
        with patch("shared_utils.traducao._traduzir_aws_translate") as mock_aws:
            fn = criar_traduzir_fn_com_aws_translate(traduzir_fn_primario, max_chamadas=5)
            result = fn("")
        assert result == ""
        mock_aws.assert_not_called()

    def test_max_chamadas_zero_desliga_fallback(self):
        traduzir_fn_primario = MagicMock(return_value="Hello")
        with patch("shared_utils.traducao._traduzir_aws_translate") as mock_aws:
            fn = criar_traduzir_fn_com_aws_translate(traduzir_fn_primario, max_chamadas=0)
            result = fn("Hello")
        assert result == "Hello"
        mock_aws.assert_not_called()

    def test_para_de_chamar_aws_translate_apos_cap_esgotado(self):
        traduzir_fn_primario = MagicMock(side_effect=lambda t: t)
        with patch("shared_utils.traducao._traduzir_aws_translate", return_value="traduzido") as mock_aws:
            fn = criar_traduzir_fn_com_aws_translate(traduzir_fn_primario, max_chamadas=1)
            r1 = fn("A")
            r2 = fn("B")
        assert r1 == "traduzido"
        assert r2 == "B"
        assert mock_aws.call_count == 1

    def test_usa_region_informada(self):
        traduzir_fn_primario = MagicMock(return_value="Hello")
        with patch("shared_utils.traducao._traduzir_aws_translate", return_value="ok") as mock_aws:
            fn = criar_traduzir_fn_com_aws_translate(traduzir_fn_primario, max_chamadas=1, region="us-east-1")
            fn("Hello")
        mock_aws.assert_called_once_with("Hello", "us-east-1")

    def test_thread_safety_nao_ultrapassa_cap_sob_concorrencia(self):
        traduzir_fn_primario = MagicMock(side_effect=lambda t: t)
        with patch("shared_utils.traducao._traduzir_aws_translate", return_value="traduzido") as mock_aws:
            fn = criar_traduzir_fn_com_aws_translate(traduzir_fn_primario, max_chamadas=5)
            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(fn, [f"texto{i}" for i in range(20)]))
        assert mock_aws.call_count == 5


class TestElegivelOverviewPt:
    def test_elegivel_quando_en_e_overview_preenchido(self):
        df = pd.DataFrame({"original_language": ["en"], "overview_en": ["Hello"]})
        assert elegivel_overview_pt(df).tolist() == [True]

    def test_elegivel_para_qualquer_idioma_diferente_de_pt(self):
        df = pd.DataFrame({
            "original_language": ["fr", "ja", "es"],
            "overview_en": ["Bonjour", "Konnichiwa", "Hola"],
        })
        assert elegivel_overview_pt(df).tolist() == [True, True, True]

    def test_nao_elegivel_quando_idioma_e_pt(self):
        df = pd.DataFrame({"original_language": ["pt"], "overview_en": ["Olá"]})
        assert elegivel_overview_pt(df).tolist() == [False]

    def test_nao_elegivel_quando_overview_en_vazio_ou_nulo(self):
        df = pd.DataFrame({"original_language": ["en", "en"], "overview_en": ["", None]})
        assert elegivel_overview_pt(df).tolist() == [False, False]


class TestElegivelTaglinePt:
    def test_elegivel_para_qualquer_idioma_diferente_de_pt(self):
        df = pd.DataFrame({
            "original_language": ["en", "fr"],
            "tagline": ["Slogan A", "Slogan B"],
        })
        assert elegivel_tagline_pt(df).tolist() == [True, True]

    def test_nao_elegivel_quando_idioma_e_pt(self):
        df = pd.DataFrame({"original_language": ["pt"], "tagline": ["Já em português"]})
        assert elegivel_tagline_pt(df).tolist() == [False]

    def test_nao_elegivel_quando_tagline_vazia_ou_nula(self):
        df = pd.DataFrame({"original_language": ["en", "en"], "tagline": ["", None]})
        assert elegivel_tagline_pt(df).tolist() == [False, False]


class TestElegivelKeywordsPt:
    def test_elegivel_para_qualquer_idioma_diferente_de_pt(self):
        df = pd.DataFrame({"original_language": ["en", "fr"], "keywords": ["action, drama", "espion"]})
        assert elegivel_keywords_pt(df).tolist() == [True, True]

    def test_nao_elegivel_quando_idioma_e_pt(self):
        df = pd.DataFrame({"original_language": ["pt"], "keywords": ["ação, drama"]})
        assert elegivel_keywords_pt(df).tolist() == [False]

    def test_nao_elegivel_quando_keywords_vazias_ou_nulas(self):
        df = pd.DataFrame({"original_language": ["en", "en"], "keywords": ["", None]})
        assert elegivel_keywords_pt(df).tolist() == [False, False]
