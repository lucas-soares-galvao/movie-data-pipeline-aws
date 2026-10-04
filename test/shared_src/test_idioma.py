from unittest.mock import patch

import pandas as pd
from shared_utils.idioma import add_detected_language_column


class TestAddDetectedLanguageColumn:
    def test_aplica_detect_fn_a_cada_linha(self):
        df = pd.DataFrame({"texto": ["Hello", "Olá", None]})
        def detect_fn(t):
            return {"Hello": "en", "Olá": "pt", "": None}[t]
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
        # new=<função simples> (não MagicMock): pandas.Series.apply trata um Mock como
        # list-like (__iter__ configurado por padrão em MagicMock) e tenta agregar em
        # vez de chamar por elemento — new= troca o atributo pelo objeto exato, sem
        # wrapper de Mock.
        df = pd.DataFrame({"texto": ["Hello"]})
        calls = []

        def fake_detect(t):
            calls.append(t)
            return "en"

        with patch("shared_utils.idioma.detect_language_llm", new=fake_detect):
            result = add_detected_language_column(df, "texto", "detected_language")
        assert result["detected_language"].tolist() == ["en"]
        assert calls == ["Hello"]

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
        def detect_fn(t):
            return chamados.append(t) or "pt"
        result = add_detected_language_column(df, "texto", "detected_language", detect_fn, only_missing=True)
        assert result["detected_language"].tolist() == ["en", "pt"]
        assert chamados == ["Olá"]

    def test_only_missing_true_cria_coluna_ausente_e_detecta_tudo(self):
        df = pd.DataFrame({"texto": ["Hello"]})
        result = add_detected_language_column(df, "texto", "detected_language", lambda t: "en", only_missing=True)
        assert result["detected_language"].tolist() == ["en"]
