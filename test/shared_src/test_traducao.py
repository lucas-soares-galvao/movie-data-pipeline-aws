from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import MagicMock, patch

import pandas as pd

from shared_utils.traducao import (
    eligible_keywords_pt,
    eligible_overview_pt,
    eligible_tagline_pt,
    is_translated_mask,
    reuse_existing_translation,
    resolve_translate_fn,
    translate_pending_column,
    translate_in_parallel,
)


class TestResolveTranslateFn:
    def test_resolve_google_usa_google_como_primario(self):
        fn = resolve_translate_fn("google", lambda t: f"[G]{t}", lambda t: f"[A]{t}")
        assert fn("Hello") == "[G]Hello"

    def test_resolve_aws_usa_aws_como_primario(self):
        fn = resolve_translate_fn("aws", lambda t: f"[G]{t}", lambda t: f"[A]{t}")
        assert fn("Hello") == "[A]Hello"

    def test_provider_invalido_levanta_value_error(self):
        with pytest.raises(ValueError, match="TRANSLATE_PROVIDER inválido"):
            resolve_translate_fn("deepl")

    def test_usa_referencias_locais_informadas_pelo_chamador(self):
        """translate_google/translate_aws são parâmetros (não resolvidos via módulo)
        para que um chamador que faça patch da própria referência local (ex.:
        patch("src.utils.translate_text", ...)) continue funcionando."""
        fn_google = MagicMock(side_effect=lambda t: f"[G]{t}")
        fn_aws = MagicMock(side_effect=lambda t: f"[A]{t}")

        resolve_translate_fn("google", fn_google, fn_aws)("Hello")
        fn_google.assert_called_once_with("Hello")

        resolve_translate_fn("aws", fn_google, fn_aws)("Hello")
        fn_aws.assert_called_once_with("Hello")

    def test_fallback_disparado_quando_primario_falha(self):
        """Primário devolve o próprio texto (sinal de falha) — cai para o fallback."""
        primario = MagicMock(side_effect=lambda t: t)
        fallback = MagicMock(side_effect=lambda t: f"[fallback]{t}")

        fn = resolve_translate_fn("aws", translate_google=fallback, translate_aws=primario)

        assert fn("Hello") == "[fallback]Hello"
        fallback.assert_called_once_with("Hello")

    def test_fallback_nao_disparado_quando_primario_funciona(self):
        primario = MagicMock(side_effect=lambda t: f"[ok]{t}")
        fallback = MagicMock()

        fn = resolve_translate_fn("aws", translate_google=fallback, translate_aws=primario)

        assert fn("Hello") == "[ok]Hello"
        fallback.assert_not_called()

    def test_texto_vazio_nao_dispara_fallback(self):
        primario = MagicMock(side_effect=lambda t: t)
        fallback = MagicMock()

        fn = resolve_translate_fn("aws", translate_google=fallback, translate_aws=primario)

        assert fn("") == ""
        fallback.assert_not_called()

    def test_cap_por_caracteres_bloqueia_excedente(self):
        """provider="google": AWS é o fallback pago — limitado por aws_fallback_max_chars."""
        primario_google = MagicMock(side_effect=lambda t: t)
        fallback_aws = MagicMock(side_effect=lambda t: f"[aws]{t}")

        fn = resolve_translate_fn(
            "google", translate_google=primario_google, translate_aws=fallback_aws,
            aws_fallback_max_chars=5,
        )

        assert fn("Hello") == "[aws]Hello"  # consome os 5 caracteres do orçamento
        assert fn("Hi") == "Hi"  # orçamento esgotado — devolve o texto original sem chamar o fallback
        fallback_aws.assert_called_once_with("Hello")

    def test_cap_nao_se_aplica_quando_aws_e_primario(self):
        """provider="aws": Google é o fallback (grátis) — sem limite de caracteres."""
        primario_aws = MagicMock(side_effect=lambda t: t)  # sempre "falha"
        fallback_google = MagicMock(side_effect=lambda t: f"[google]{t}")

        fn = resolve_translate_fn(
            "aws", translate_google=fallback_google, translate_aws=primario_aws,
            aws_fallback_max_chars=1,  # cap minúsculo — não deve importar, pois aws é o primário
        )

        for texto in ("Hello", "World", "Another long text"):
            assert fn(texto) == f"[google]{texto}"
        assert fallback_google.call_count == 3

    def test_cap_thread_safe_sob_concorrencia(self):
        """O orçamento de caracteres nunca é ultrapassado mesmo com chamadas concorrentes."""
        primario_google = MagicMock(side_effect=lambda t: t)
        fallback_aws = MagicMock(side_effect=lambda t: f"[aws]{t}")

        fn = resolve_translate_fn(
            "google", translate_google=primario_google, translate_aws=fallback_aws,
            aws_fallback_max_chars=10,
        )
        textos = ["ab"] * 20  # 20 x 2 caracteres = 40 caracteres pedidos, orçamento de 10

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(fn, textos))

        # orçamento de 10 caracteres / textos de 2 caracteres cada = no máximo 5 chamadas ao fallback
        assert fallback_aws.call_count <= 5


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
    def test_elegivel_quando_overview_en_preenchido(self):
        df = pd.DataFrame({"overview_en": ["Hello", "Bonjour", "Hola"]})
        assert eligible_overview_pt(df).tolist() == [True, True, True]

    def test_elegivel_mesmo_com_original_language_pt(self):
        """original_language não é critério de elegibilidade: é o idioma de
        produção original do título, não o idioma do texto retornado pela API —
        não há garantia de que overview_en já esteja em português quando
        original_language == 'pt' (ver docstring de eligible_overview_pt)."""
        df = pd.DataFrame({"original_language": ["pt"], "overview_en": ["Overview em inglês"]})
        assert eligible_overview_pt(df).tolist() == [True]

    def test_nao_elegivel_quando_overview_en_vazio_ou_nulo(self):
        df = pd.DataFrame({"overview_en": ["", None]})
        assert eligible_overview_pt(df).tolist() == [False, False]

    def test_nao_elegivel_quando_idioma_detectado_ja_e_pt(self):
        """overview_idioma_detectado == 'pt' exclui o registro do lote de tradução —
        evita reenviar ao Google/AWS um texto já confirmado em português (otimização
        contra retradução infinita, ver shared_utils.idioma)."""
        df = pd.DataFrame({
            "overview_en": ["Já em português", "Ainda em inglês"],
            "overview_idioma_detectado": ["pt", "en"],
        })
        assert eligible_overview_pt(df).tolist() == [False, True]

    def test_elegivel_quando_coluna_idioma_detectado_nao_existe(self):
        """Compatibilidade: chamadores/testes que não pré-computam a detecção de
        idioma continuam funcionando como antes (nada é excluído)."""
        df = pd.DataFrame({"overview_en": ["Hello"]})
        assert "overview_idioma_detectado" not in df.columns
        assert eligible_overview_pt(df).tolist() == [True]


class TestEligibleTaglinePt:
    def test_elegivel_quando_tagline_preenchida(self):
        df = pd.DataFrame({"tagline": ["Slogan A", "Slogan B"]})
        assert eligible_tagline_pt(df).tolist() == [True, True]

    def test_elegivel_mesmo_com_original_language_pt(self):
        df = pd.DataFrame({"original_language": ["pt"], "tagline": ["Tagline em inglês"]})
        assert eligible_tagline_pt(df).tolist() == [True]

    def test_nao_elegivel_quando_tagline_vazia_ou_nula(self):
        df = pd.DataFrame({"tagline": ["", None]})
        assert eligible_tagline_pt(df).tolist() == [False, False]

    def test_nao_elegivel_quando_idioma_detectado_ja_e_pt(self):
        df = pd.DataFrame({
            "tagline": ["Já em português", "Ainda em inglês"],
            "tagline_idioma_detectado": ["pt", "en"],
        })
        assert eligible_tagline_pt(df).tolist() == [False, True]


class TestEligibleKeywordsPt:
    def test_elegivel_quando_keywords_preenchidas(self):
        df = pd.DataFrame({"keywords": ["action, drama", "espion"]})
        assert eligible_keywords_pt(df).tolist() == [True, True]

    def test_elegivel_mesmo_com_original_language_pt(self):
        """Keywords não são localizadas pela API do TMDB — continuam em inglês
        mesmo para títulos com original_language == 'pt'."""
        df = pd.DataFrame({"original_language": ["pt"], "keywords": ["action, drama"]})
        assert eligible_keywords_pt(df).tolist() == [True]

    def test_nao_elegivel_quando_keywords_vazias_ou_nulas(self):
        df = pd.DataFrame({"keywords": ["", None]})
        assert eligible_keywords_pt(df).tolist() == [False, False]

    def test_nao_elegivel_quando_idioma_detectado_ja_e_pt(self):
        df = pd.DataFrame({
            "keywords": ["ação, suspense", "action, drama"],
            "keywords_idioma_detectado": ["pt", "en"],
        })
        assert eligible_keywords_pt(df).tolist() == [False, True]


class TestIsTranslatedMask:
    def test_true_quando_preenchido_e_diferente_da_fonte(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": ["Olá"]})
        assert is_translated_mask(df, "overview_en", "overview_pt").tolist() == [True]

    def test_false_quando_destino_vazio_ou_nulo(self):
        df = pd.DataFrame({"overview_en": ["Hello", "Hi"], "overview_pt": ["", None]})
        assert is_translated_mask(df, "overview_en", "overview_pt").tolist() == [False, False]

    def test_false_quando_destino_igual_a_fonte(self):
        """Destino igual à fonte indica tradução que falhou (ver
        translate_text/translate_text_aws) — continua pendente."""
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": ["Hello"]})
        assert is_translated_mask(df, "overview_en", "overview_pt").tolist() == [False]

    def test_false_quando_coluna_destino_nao_existe(self):
        df = pd.DataFrame({"overview_en": ["Hello"]})
        assert is_translated_mask(df, "overview_en", "overview_pt").tolist() == [False]

    def test_already_native_mask_true_conta_como_traduzido_mesmo_igual_a_fonte(self):
        """Cobre o caso 'fonte já era pt-BR, copiada direto' — target == source, mas
        o registro deve contar como traduzido porque a fonte já estava correta."""
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": ["Já em português"]})
        already_native = pd.Series([True])
        assert is_translated_mask(df, "overview_en", "overview_pt", already_native_mask=already_native).tolist() == [True]

    def test_already_native_mask_false_nao_conta_quando_igual_a_fonte(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": ["Hello"]})
        already_native = pd.Series([False])
        assert is_translated_mask(df, "overview_en", "overview_pt", already_native_mask=already_native).tolist() == [False]

    def test_already_native_mask_nao_afeta_quando_destino_vazio(self):
        """already_native_mask não faz um registro sem tradução nenhuma contar como
        traduzido — target ainda precisa estar preenchido."""
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        already_native = pd.Series([True])
        assert is_translated_mask(df, "overview_en", "overview_pt", already_native_mask=already_native).tolist() == [False]
