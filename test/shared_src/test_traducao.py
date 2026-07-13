import pytest
from unittest.mock import MagicMock, patch

import pandas as pd

from shared_utils.traducao import (
    eligible_keywords_pt,
    eligible_overview_pt,
    eligible_tagline_pt,
    reuse_existing_translation,
    resolve_translate_fn,
    translate_pending_column,
    translate_in_parallel,
    translate_text,
    translate_text_aws,
)


class TestResolveTranslateFn:
    def test_resolve_google(self):
        assert resolve_translate_fn("google") is translate_text

    def test_resolve_aws(self):
        assert resolve_translate_fn("aws") is translate_text_aws

    def test_provider_invalido_levanta_value_error(self):
        with pytest.raises(ValueError, match="TRANSLATE_PROVIDER inválido"):
            resolve_translate_fn("deepl")

    def test_usa_referencias_locais_informadas_pelo_chamador(self):
        """translate_google/translate_aws são parâmetros (não resolvidos via módulo)
        para que um chamador que faça patch da própria referência local (ex.:
        patch("src.utils.translate_text", ...)) continue funcionando."""
        fn_google = MagicMock()
        fn_aws = MagicMock()
        assert resolve_translate_fn("google", fn_google, fn_aws) is fn_google
        assert resolve_translate_fn("aws", fn_google, fn_aws) is fn_aws


class TestTranslateInParallel:
    def test_traduz_cada_valor_e_preserva_a_ordem(self):
        traduzir_fn = MagicMock(side_effect=lambda t: f"[PT] {t}")
        resultado = translate_in_parallel(["Hello", "World"], traduzir_fn)
        assert resultado == ["[PT] Hello", "[PT] World"]

    def test_lista_vazia_nao_chama_traduzir_fn(self):
        traduzir_fn = MagicMock()
        assert translate_in_parallel([], traduzir_fn) == []
        traduzir_fn.assert_not_called()

    def test_usa_max_workers_informado(self):
        """max_workers é repassado ao ThreadPoolExecutor, não hardcoded."""
        with patch("shared_utils.traducao.ThreadPoolExecutor") as mock_executor_cls:
            mock_executor = mock_executor_cls.return_value.__enter__.return_value
            mock_executor.map.return_value = iter(["ok"])
            translate_in_parallel(["Hello"], MagicMock(), max_workers=3)
        mock_executor_cls.assert_called_once_with(max_workers=3)


class TestTranslatePendingColumn:
    def test_traduz_registros_elegiveis_pendentes(self):
        df = pd.DataFrame({"fonte": ["Hello", "World"], "destino": [None, None]})
        traduzir_fn = MagicMock(side_effect=lambda t: f"[PT] {t}")
        mask = pd.Series([True, True])

        sucesso = translate_pending_column(df, "fonte", "destino", mask, traduzir_fn)

        assert sucesso == 2
        assert df["destino"].tolist() == ["[PT] Hello", "[PT] World"]

    def test_cria_coluna_destino_se_nao_existir(self):
        df = pd.DataFrame({"fonte": ["Hello"]})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        translate_pending_column(df, "fonte", "destino", pd.Series([True]), traduzir_fn)

        assert df["destino"].tolist() == ["Olá"]

    def test_pula_registro_ja_traduzido_com_sucesso(self):
        """destino preenchido e diferente da fonte: não é retraduzido."""
        df = pd.DataFrame({"fonte": ["Hello"], "destino": ["Olá"]})
        traduzir_fn = MagicMock()

        sucesso = translate_pending_column(df, "fonte", "destino", pd.Series([True]), traduzir_fn)

        assert sucesso == 0
        assert df["destino"].tolist() == ["Olá"]
        traduzir_fn.assert_not_called()

    def test_retenta_quando_destino_igual_a_fonte(self):
        """destino == fonte indica uma tradução que falhou em um run
        anterior (ver translate_text/translate_text_aws) — deve ser retentado, não pulado."""
        df = pd.DataFrame({"fonte": ["Hello"], "destino": ["Hello"]})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        sucesso = translate_pending_column(df, "fonte", "destino", pd.Series([True]), traduzir_fn)

        assert sucesso == 1
        assert df["destino"].tolist() == ["Olá"]

    def test_nao_elegivel_nao_e_traduzido(self):
        df = pd.DataFrame({"fonte": ["Hello"], "destino": [None]})
        traduzir_fn = MagicMock()

        sucesso = translate_pending_column(df, "fonte", "destino", pd.Series([False]), traduzir_fn)

        assert sucesso == 0
        traduzir_fn.assert_not_called()

    def test_mask_vazia_nao_chama_traduzir_fn(self):
        df = pd.DataFrame({"fonte": [], "destino": []})
        traduzir_fn = MagicMock()

        sucesso = translate_pending_column(df, "fonte", "destino", pd.Series([], dtype=bool), traduzir_fn)

        assert sucesso == 0
        traduzir_fn.assert_not_called()

    def test_sucesso_nao_conta_quando_traducao_falha_e_mantem_original(self):
        """traduzir_fn pode devolver o próprio texto original em caso de falha
        (ver translate_text); esses casos não contam como sucesso."""
        df = pd.DataFrame({"fonte": ["Hello", "World"], "destino": [None, None]})
        traduzir_fn = MagicMock(side_effect=lambda t: t if t == "Hello" else f"[PT] {t}")

        sucesso = translate_pending_column(df, "fonte", "destino", pd.Series([True, True]), traduzir_fn)

        assert sucesso == 1
        assert df["destino"].tolist() == ["Hello", "[PT] World"]

    def test_usa_max_workers_informado(self):
        with patch("shared_utils.traducao.translate_in_parallel") as mock_paralelo:
            mock_paralelo.return_value = ["Olá"]
            df = pd.DataFrame({"fonte": ["Hello"], "destino": [None]})
            translate_pending_column(df, "fonte", "destino", pd.Series([True]), MagicMock(), max_workers=3)
        assert mock_paralelo.call_args.kwargs["max_workers"] == 3


class TestReuseExistingTranslation:
    def test_reaproveita_quando_fonte_identica(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": ["Traduzido antes"]})
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert result["overview_pt"].iloc[0] == "Traduzido antes"

    def test_nao_reaproveita_quando_fonte_mudou(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse nova"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse antiga"], "overview_pt": ["Traduzido antes"]})
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_nao_reaproveita_id_novo_sem_historico(self):
        df = pd.DataFrame({"id": [2], "overview_en": ["Sinopse"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": ["Traduzido antes"]})
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_df_anterior_none_nao_quebra(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        result = reuse_existing_translation(df, None, "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_df_anterior_vazio_nao_quebra(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        result = reuse_existing_translation(df, pd.DataFrame(), "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_nao_sobrescreve_destino_ja_preenchido(self):
        """Prioridade da tradução nativa do TMDB (já atribuída ao df novo) é preservada."""
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": ["Tradução nativa TMDB"]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": ["Traduzido antes"]})
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert result["overview_pt"].iloc[0] == "Tradução nativa TMDB"

    def test_ignora_schema_antigo_sem_coluna(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"]})  # sem overview_pt
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert pd.isna(result["overview_pt"].iloc[0])

    def test_ids_duplicados_no_df_anterior_usa_ultimo(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Sinopse"], "overview_pt": [None]})
        df_anterior = pd.DataFrame({
            "id": [1, 1],
            "overview_en": ["Sinopse", "Sinopse"],
            "overview_pt": ["Traducao antiga", "Traducao mais recente"],
        })
        result = reuse_existing_translation(df, df_anterior, "overview_en", "overview_pt")
        assert result["overview_pt"].iloc[0] == "Traducao mais recente"

    def test_coluna_chave_customizada(self):
        """glue_etl usa key_column='iso_3166_1'/'iso_639_1' em vez do default 'id'."""
        df = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"], "name_pt": [None]})
        df_anterior = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"], "name_pt": ["Brasil"]})
        result = reuse_existing_translation(
            df, df_anterior, "english_name", "name_pt", key_column="iso_3166_1"
        )
        assert result["name_pt"].iloc[0] == "Brasil"

    def test_coluna_chave_customizada_nao_reaproveita_quando_ausente_no_anterior(self):
        df = pd.DataFrame({"iso_3166_1": ["BR"], "english_name": ["Brazil"], "name_pt": [None]})
        df_anterior = pd.DataFrame({"iso_3166_1": ["US"], "english_name": ["United States"], "name_pt": ["Estados Unidos"]})
        result = reuse_existing_translation(
            df, df_anterior, "english_name", "name_pt", key_column="iso_3166_1"
        )
        assert pd.isna(result["name_pt"].iloc[0])


class TestEligibleOverviewPt:
    def test_elegivel_quando_en_e_overview_preenchido(self):
        df = pd.DataFrame({"original_language": ["en"], "overview_en": ["Hello"]})
        assert eligible_overview_pt(df).tolist() == [True]

    def test_elegivel_para_qualquer_idioma_diferente_de_pt(self):
        df = pd.DataFrame({
            "original_language": ["fr", "ja", "es"],
            "overview_en": ["Bonjour", "Konnichiwa", "Hola"],
        })
        assert eligible_overview_pt(df).tolist() == [True, True, True]

    def test_nao_elegivel_quando_idioma_e_pt(self):
        df = pd.DataFrame({"original_language": ["pt"], "overview_en": ["Olá"]})
        assert eligible_overview_pt(df).tolist() == [False]

    def test_nao_elegivel_quando_overview_en_vazio_ou_nulo(self):
        df = pd.DataFrame({"original_language": ["en", "en"], "overview_en": ["", None]})
        assert eligible_overview_pt(df).tolist() == [False, False]


class TestEligibleTaglinePt:
    def test_elegivel_para_qualquer_idioma_diferente_de_pt(self):
        df = pd.DataFrame({
            "original_language": ["en", "fr"],
            "tagline": ["Slogan A", "Slogan B"],
        })
        assert eligible_tagline_pt(df).tolist() == [True, True]

    def test_nao_elegivel_quando_idioma_e_pt(self):
        df = pd.DataFrame({"original_language": ["pt"], "tagline": ["Já em português"]})
        assert eligible_tagline_pt(df).tolist() == [False]

    def test_nao_elegivel_quando_tagline_vazia_ou_nula(self):
        df = pd.DataFrame({"original_language": ["en", "en"], "tagline": ["", None]})
        assert eligible_tagline_pt(df).tolist() == [False, False]


class TestEligibleKeywordsPt:
    def test_elegivel_para_qualquer_idioma_diferente_de_pt(self):
        df = pd.DataFrame({"original_language": ["en", "fr"], "keywords": ["action, drama", "espion"]})
        assert eligible_keywords_pt(df).tolist() == [True, True]

    def test_nao_elegivel_quando_idioma_e_pt(self):
        df = pd.DataFrame({"original_language": ["pt"], "keywords": ["ação, drama"]})
        assert eligible_keywords_pt(df).tolist() == [False]

    def test_nao_elegivel_quando_keywords_vazias_ou_nulas(self):
        df = pd.DataFrame({"original_language": ["en", "en"], "keywords": ["", None]})
        assert eligible_keywords_pt(df).tolist() == [False, False]
