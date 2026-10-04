from unittest.mock import MagicMock, patch

import pandas as pd
from shared_utils.traducao import (
    resolve_pt_translation,
    reuse_existing_translation,
    translate_in_parallel,
)


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
        def detect_fn(t):
            return "en"
        traduzir_fn = MagicMock(side_effect=lambda t: f"[PT] {t}")

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert sucesso == 2
        assert df["overview_pt"].tolist() == ["[PT] Hello", "[PT] World"]

    def test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_tradutor(self):
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": [None]})
        def detect_fn(t):
            return "pt"
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
        def detect_fn(t):
            return "en"
        traduzir_fn = MagicMock(side_effect=lambda t: t)  # tradução "falha" (devolve igual)

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", detect_fn, traduzir_fn,
        )

        assert df["overview_tentativas"].iloc[0] == 1

    def test_copia_direta_nao_incrementa_tentativas(self):
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": [None]})
        def detect_fn(t):
            return "pt"
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
            "overview_tentativas", lambda t: "en", traduzir_fn, max_attempts=3,
        )

        assert sucesso == 0
        traduzir_fn.assert_not_called()
        assert df["overview_tentativas"].iloc[0] == 3

    def test_cria_coluna_tentativas_como_zero_quando_ausente(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        def detect_fn(t):
            return "en"
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

    def test_precisa_traducao_column_none_nao_cria_coluna(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá")

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn,
        )

        assert "overview_needs_translation" not in df.columns

    def test_precisa_traducao_true_quando_resultado_ainda_nao_e_pt(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        traduzir_fn = MagicMock(side_effect=lambda t: t)  # tradução "falha" (devolve igual)

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn,
            needs_translation_column="overview_needs_translation",
        )

        assert df["overview_needs_translation"].tolist() == [True]

    def test_precisa_traducao_false_quando_resultado_ja_e_pt(self):
        df = pd.DataFrame({"overview_en": ["Já em português"], "overview_pt": [None]})
        traduzir_fn = MagicMock()

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "pt", traduzir_fn,
            needs_translation_column="overview_needs_translation",
        )

        assert df["overview_needs_translation"].tolist() == [False]

    def test_precisa_traducao_false_quando_fonte_vazia(self):
        df = pd.DataFrame({"overview_en": [None], "overview_pt": [None]})
        traduzir_fn = MagicMock()

        df, _ = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: None, traduzir_fn,
            needs_translation_column="overview_needs_translation",
        )

        assert df["overview_needs_translation"].tolist() == [False]

    def test_loga_resumo_agregado_de_falhas_de_traducao(self, caplog):
        """Falhas de tradução não devem ser logadas uma a uma (isso fica em DEBUG
        dentro de translate_text_llm) — só o resumo agregado
        (falhas / elegíveis) aparece aqui, em INFO."""
        import logging
        df = pd.DataFrame({"overview_en": ["Hello", "World"], "overview_pt": [None, None]})
        def detect_fn(t):
            return "en"
        # "Hello" traduz com sucesso; "World" "falha" (tradutor devolve o próprio texto).
        traduzir_fn = MagicMock(side_effect=lambda t: "Olá" if t == "Hello" else t)

        with caplog.at_level(logging.INFO):
            df, sucesso = resolve_pt_translation(
                df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
                "overview_tentativas", detect_fn, traduzir_fn,
            )

        assert sucesso == 1
        assert "1 falha" in caplog.text
        assert "2 elegível" in caplog.text

    def test_precisa_traducao_continua_true_mesmo_com_tentativas_esgotadas(self):
        """Diferente da elegibilidade (que para de tentar), a coluna de estado
        continua True: o campo ainda não está em português, mesmo que o pipeline
        já tenha desistido de reenviar essa linha ao tradutor."""
        df = pd.DataFrame({
            "overview_en": ["Iron Man"],
            "overview_pt": ["Iron Man"],
            "overview_idioma_pt": ["en"],
            "overview_tentativas": [3],
        })
        traduzir_fn = MagicMock()

        df, sucesso = resolve_pt_translation(
            df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
            "overview_tentativas", lambda t: "en", traduzir_fn, max_attempts=3,
            needs_translation_column="overview_needs_translation",
        )

        assert sucesso == 0
        traduzir_fn.assert_not_called()
        assert df["overview_needs_translation"].tolist() == [True]
