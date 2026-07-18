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
        result = add_detected_language_column(df, "texto", "idioma_detectado", detect_fn)
        assert result["idioma_detectado"].iloc[0] == "en"
        assert result["idioma_detectado"].iloc[1] == "pt"
        assert pd.isna(result["idioma_detectado"].iloc[2])

    def test_nan_tratado_como_string_vazia(self):
        df = pd.DataFrame({"texto": [float("nan")]})
        recebido = {}

        def detect_fn(t):
            recebido["valor"] = t
            return None

        add_detected_language_column(df, "texto", "idioma_detectado", detect_fn)
        assert recebido["valor"] == ""

    def test_default_detect_fn_usado_quando_nao_informado(self):
        df = pd.DataFrame({"texto": ["This is a clearly written English sentence with enough words."]})
        result = add_detected_language_column(df, "texto", "idioma_detectado")
        assert result["idioma_detectado"].tolist() == ["en"]

    def test_modifica_df_in_place_e_retorna_mesma_referencia(self):
        df = pd.DataFrame({"texto": ["Hello"]})
        result = add_detected_language_column(df, "texto", "idioma_detectado", lambda t: "en")
        assert result is df
        assert "idioma_detectado" in df.columns
