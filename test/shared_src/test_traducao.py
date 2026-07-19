from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import MagicMock, patch

import pandas as pd

from shared_utils.traducao import (
    resolve_pt_translation,
    reuse_existing_translation,
    resolve_translate_fn,
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


class TestResolvePtTranslation:
    def _detect_fn(self, mapping):
        return lambda t: mapping.get(t)

    def test_traduz_registros_elegiveis_pendentes(self):
        df = pd.DataFrame({"overview_en": ["Hello", "World"], "overview_pt": [None, None]})
        detect_fn = lambda t: "en"  # noqa: E731 — sempre "não-pt" para forçar elegibilidade
        traduzir_fn = MagicMock(side_effect=lambda t: f"[PT] {t}")

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 2
        assert df["overview_pt"].tolist() == ["[PT] Hello", "[PT] World"]

    def test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_tradutor(self):
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": [None]})
        detect_fn = lambda t: "pt"  # noqa: E731
        traduzir_fn = MagicMock()

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 0
        assert df["overview_pt"].iloc[0] == "Já em português"
        assert df["overview_idioma_pt"].iloc[0] == "pt"
        assert df["overview_tentativas"].iloc[0] == 0
        traduzir_fn.assert_not_called()

    def test_elegibilidade_usa_idioma_do_destino_nao_diff_de_string(self):
        """Um destino que difere da fonte mas cujo idioma detectado não é 'pt'
        (ex.: mistradução silenciosa) continua elegível — diferente da antiga
        heurística de string-diff, que consideraria isso 'já traduzido'."""
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": ["Bonjour"],  # traduziu errado, pra francês
            "overview_idioma_en": ["en"],
        })
        detect_fn = self._detect_fn({"Hello": "en", "Bonjour": "fr", "Olá": "pt"})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 1
        assert df["overview_pt"].iloc[0] == "Olá"
        assert df["overview_idioma_pt"].iloc[0] == "pt"

    def test_nao_retraduz_quando_idioma_pt_ja_confirmado(self):
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": ["Olá"],
            "overview_idioma_pt": ["pt"],
        })
        traduzir_fn = MagicMock()

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn,
        )

        assert sucesso == 0
        traduzir_fn.assert_not_called()

    def test_redetecta_idioma_pt_so_nas_linhas_recem_traduzidas(self):
        """A detecção feita antes da tradução (sobre o valor antigo/vazio de
        overview_pt) fica obsoleta para as linhas traduzidas nesta execução — só
        essas devem ser redetectadas a partir do novo valor."""
        df = pd.DataFrame({
            "overview_en": ["Hello", "World"],
            "overview_pt": [None, None],
            "overview_idioma_pt": [None, "en"],  # linha 2: já detectado antes (não-pt)
        })
        detect_fn = self._detect_fn({"Hello": "en", "World": "en", "Olá": "pt", "Mundo": "pt"})
        traduzir_fn = MagicMock(side_effect=lambda t: {"Hello": "Olá", "World": "Mundo"}[t])

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 2
        assert df["overview_idioma_pt"].tolist() == ["pt", "pt"]

    def test_incrementa_tentativas_para_linhas_elegiveis(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        detect_fn = lambda t: "en"  # noqa: E731 — nunca confirma pt
        traduzir_fn = MagicMock(side_effect=lambda t: t)  # tradução "falha" (devolve igual)

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert df["overview_tentativas"].iloc[0] == 1

    def test_copia_direta_nao_incrementa_tentativas(self):
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": [None]})
        detect_fn = lambda t: "pt"  # noqa: E731
        traduzir_fn = MagicMock()

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert df["overview_tentativas"].iloc[0] == 0

    def test_esgota_tentativas_e_para_de_reenviar_ao_tradutor(self):
        """Conteúdo genuinamente não traduzível (nome próprio, termo curto) nunca
        teria idioma_pt == 'pt' — sem o teto, seria retentado para sempre."""
        df = pd.DataFrame({
            "overview_en": ["Iron Man"],
            "overview_pt": ["Iron Man"],
            "overview_idioma_pt": ["en"],
            "overview_tentativas": [3],
        })
        traduzir_fn = MagicMock()

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn, max_tentativas=3,
        )

        assert sucesso == 0
        traduzir_fn.assert_not_called()
        assert df["overview_tentativas"].iloc[0] == 3

    def test_cria_coluna_tentativas_como_zero_quando_ausente(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        detect_fn = lambda t: "en"  # noqa: E731
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert "overview_tentativas" in df.columns

    def test_only_missing_nao_recalcula_idioma_en_ja_preenchido(self):
        df = pd.DataFrame({
            "overview_en": ["Hello"],
            "overview_pt": ["Olá"],
            "overview_idioma_en": ["antigo"],
            "overview_idioma_pt": ["pt"],
        })
        detect_fn = MagicMock()

        resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, MagicMock(),
        )

        assert df["overview_idioma_en"].iloc[0] == "antigo"
        detect_fn.assert_not_called()

    def test_usa_max_workers_informado(self):
        with patch("shared_utils.traducao.translate_in_parallel") as mock_paralelo:
            mock_paralelo.return_value = ["Olá"]
            df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
            resolve_pt_translation(
                df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
                "overview_tentativas", lambda t: "en", MagicMock(), max_workers=3,
            )
        assert mock_paralelo.call_args.kwargs["max_workers"] == 3
