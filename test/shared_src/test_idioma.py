import pandas as pd

from shared_utils.idioma import add_detected_language_column, resolve_detect_language_fn


class TestResolveDetectLanguageFn:
    def test_usa_local_quando_local_detecta(self):
        fn = resolve_detect_language_fn(lambda t: "pt", lambda t: "en")
        assert fn("qualquer texto") == "pt"

    def test_cai_para_aws_quando_local_devolve_none(self):
        fn = resolve_detect_language_fn(lambda t: None, lambda t: "en")
        assert fn("qualquer texto") == "en"

    def test_aws_nao_e_chamado_quando_local_detecta(self):
        calls = []
        fn = resolve_detect_language_fn(lambda t: "pt", lambda t: calls.append(t) or "en")
        fn("texto")
        assert calls == []

    def test_orcamento_esgotado_devolve_none_sem_chamar_aws(self):
        calls = []
        fn = resolve_detect_language_fn(
            lambda t: None, lambda t: calls.append(t) or "en", aws_fallback_max_chars=3
        )
        result = fn("texto mais longo que o orcamento")
        assert result is None
        assert calls == []

    def test_orcamento_suficiente_permite_fallback_aws(self):
        fn = resolve_detect_language_fn(lambda t: None, lambda t: "en", aws_fallback_max_chars=100)
        assert fn("curto") == "en"


class TestAddDetectedLanguageColumn:
    def test_aplica_detect_fn_a_cada_linha(self):
        df = pd.DataFrame({"texto": ["Hello", "Olá", None]})
        detect_fn = lambda t: {"Hello": "en", "Olá": "pt", "": None}[t]  # noqa: E731
        result = add_detected_language_column(df, "texto", "detected_language", detect_fn)
        assert result["detected_language"].iloc[0] == "en"
        assert result["detected_language"].iloc[1] == "pt"
        assert pd.isna(result["detected_language"].iloc[2])

    def test_nan_tratado_como_string_vazia(self):
        df = pd.DataFrame({"texto": [float("nan")]})
        recebido = {}

        def detect_fn(t):
            recebido["valor"] = t
            return None

        add_detected_language_column(df, "texto", "detected_language", detect_fn)
        assert recebido["valor"] == ""

    def test_default_detect_fn_usado_quando_nao_informado(self):
        df = pd.DataFrame({"texto": ["This is a clearly written English sentence with enough words."]})
        result = add_detected_language_column(df, "texto", "detected_language")
        assert result["detected_language"].tolist() == ["en"]

    def test_modifica_df_in_place_e_retorna_mesma_referencia(self):
        df = pd.DataFrame({"texto": ["Hello"]})
        result = add_detected_language_column(df, "texto", "detected_language", lambda t: "en")
        assert result is df
        assert "detected_language" in df.columns

    def test_only_missing_false_recalcula_todas_as_linhas(self):
        df = pd.DataFrame({"texto": ["Hello", "Olá"], "detected_language": ["antigo", "antigo"]})
        result = add_detected_language_column(df, "texto", "detected_language", lambda t: "novo", only_missing=False)
        assert result["detected_language"].tolist() == ["novo", "novo"]

    def test_only_missing_true_preserva_linhas_ja_preenchidas(self):
        df = pd.DataFrame({"texto": ["Hello", "Olá"], "detected_language": ["en", None]})
        chamados = []
        detect_fn = lambda t: chamados.append(t) or "pt"  # noqa: E731
        result = add_detected_language_column(df, "texto", "detected_language", detect_fn, only_missing=True)
        assert result["detected_language"].tolist() == ["en", "pt"]
        assert chamados == ["Olá"]

    def test_only_missing_true_cria_coluna_ausente_e_detecta_tudo(self):
        df = pd.DataFrame({"texto": ["Hello"]})
        result = add_detected_language_column(df, "texto", "detected_language", lambda t: "en", only_missing=True)
        assert result["detected_language"].tolist() == ["en"]
