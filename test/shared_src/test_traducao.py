import logging
import threading
from unittest.mock import MagicMock, patch

import pandas as pd
from shared_utils.traducao import (
    detect_in_parallel,
    format_elapsed,
    resolve_pt_translation,
    reuse_detected_language,
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


class TestTranslateInParallelProgresso:
    def test_loga_progresso_a_cada_10_porcento_em_lote_grande(self, caplog):
        valores = [str(i) for i in range(20)]
        with caplog.at_level(logging.INFO):
            resultado = translate_in_parallel(valores, lambda t: t, max_workers=1, progress_label="Tradução 'x'")
        assert resultado == valores
        progresso = [r.message for r in caplog.records if r.message.startswith("Tradução 'x': ")]
        assert len(progresso) == 10
        assert "2/20 (10%)" in progresso[0]
        assert "20/20 (100%)" in progresso[-1]

    def test_nao_loga_progresso_em_lote_pequeno(self, caplog):
        valores = [str(i) for i in range(19)]
        with caplog.at_level(logging.INFO):
            translate_in_parallel(valores, lambda t: t, max_workers=1, progress_label="Tradução 'x'")
        assert not [r for r in caplog.records if r.message.startswith("Tradução 'x': ")]

    def test_sem_label_nao_loga_progresso(self, caplog):
        valores = [str(i) for i in range(20)]
        with caplog.at_level(logging.INFO):
            translate_in_parallel(valores, lambda t: t, max_workers=1)
        assert not [r for r in caplog.records if "/20" in r.message]


class TestFormatElapsed:
    def test_segundos(self):
        assert format_elapsed(0) == "0s"
        assert format_elapsed(45) == "45s"
        assert format_elapsed(59.9) == "59s"

    def test_minutos_e_segundos(self):
        assert format_elapsed(192) == "3m12s"

    def test_horas_minutos_e_segundos(self):
        assert format_elapsed(3910) == "1h05m10s"


class TestDetectInParallel:
    def test_detecta_cada_texto_e_preserva_a_ordem(self):
        resultado = detect_in_parallel(["Hello", "Olá", "Hola"], lambda t: t[:2].lower())
        assert resultado == ["he", "ol", "ho"]

    def test_lista_vazia_nao_chama_detect_fn(self):
        detect_fn = MagicMock()
        assert detect_in_parallel([], detect_fn, label="Detecção x") == []
        detect_fn.assert_not_called()

    def test_roda_em_paralelo(self):
        """Com 2 workers, as 2 chamadas esperam uma à outra na barreira; se rodassem em série
        a primeira nunca sairia dela (BrokenBarrierError por timeout)."""
        barreira = threading.Barrier(2, timeout=5)

        def detect_fn(texto):
            barreira.wait()
            return "en"

        assert detect_in_parallel(["a", "b"], detect_fn, max_workers=2) == ["en", "en"]

    def test_loga_resumo_com_detectados_e_falhas(self, caplog):
        """Texto vazio devolve None sem chamada de rede e não conta como falha."""
        respostas = {"Hello": "en", "": None, "Falha": None}
        with caplog.at_level(logging.INFO):
            detect_in_parallel(["Hello", "", "Falha"], respostas.get, label="Detecção x")
        resumo = [r.message for r in caplog.records if r.message.startswith("Detecção x: ")]
        assert len(resumo) == 1
        assert "1 detectado(s), 1 falha(s) em 3 texto(s)" in resumo[0]

    def test_sem_label_nao_loga_resumo(self, caplog):
        with caplog.at_level(logging.INFO):
            detect_in_parallel(["Hello"], lambda t: "en")
        assert "detectado(s)" not in caplog.text


class TestReuseDetectedLanguage:
    def test_reaproveita_quando_texto_identico(self):
        df = pd.DataFrame({"id": [1], "overview": ["Sinopse"]})
        anterior = pd.DataFrame({"id": [1], "overview": ["Sinopse"], "idioma": ["pt"]})
        result = reuse_detected_language(df, anterior, "overview", "idioma")
        assert result["idioma"].tolist() == ["pt"]

    def test_nao_reaproveita_quando_texto_mudou(self):
        df = pd.DataFrame({"id": [1], "overview": ["Sinopse nova"]})
        anterior = pd.DataFrame({"id": [1], "overview": ["Sinopse antiga"], "idioma": ["pt"]})
        result = reuse_detected_language(df, anterior, "overview", "idioma")
        assert result["idioma"].isna().all()

    def test_nao_reaproveita_idioma_antigo_nulo_ou_vazio(self):
        """Detecção que falhou (None) não é congelada: continua pendente para ser tentada de novo."""
        df = pd.DataFrame({"id": [1, 2], "overview": ["A", "B"]})
        anterior = pd.DataFrame({"id": [1, 2], "overview": ["A", "B"], "idioma": [None, ""]})
        result = reuse_detected_language(df, anterior, "overview", "idioma")
        assert result["idioma"].isna().all()

    def test_nao_reaproveita_texto_vazio(self):
        df = pd.DataFrame({"id": [1], "overview": [""]})
        anterior = pd.DataFrame({"id": [1], "overview": [""], "idioma": ["pt"]})
        result = reuse_detected_language(df, anterior, "overview", "idioma")
        assert result["idioma"].isna().all()

    def test_nao_sobrescreve_idioma_ja_preenchido(self):
        df = pd.DataFrame({"id": [1], "overview": ["Sinopse"], "idioma": ["en"]})
        anterior = pd.DataFrame({"id": [1], "overview": ["Sinopse"], "idioma": ["pt"]})
        result = reuse_detected_language(df, anterior, "overview", "idioma")
        assert result["idioma"].tolist() == ["en"]

    def test_id_novo_sem_historico_fica_pendente(self):
        df = pd.DataFrame({"id": [1, 2], "overview": ["A", "B"]})
        anterior = pd.DataFrame({"id": [1], "overview": ["A"], "idioma": ["pt"]})
        result = reuse_detected_language(df, anterior, "overview", "idioma")
        assert result["idioma"].iloc[0] == "pt"
        assert pd.isna(result["idioma"].iloc[1])

    def test_df_anterior_none_ou_vazio_nao_quebra_nem_cria_coluna(self):
        df = pd.DataFrame({"id": [1], "overview": ["A"]})
        assert "idioma" not in reuse_detected_language(df, None, "overview", "idioma").columns
        assert "idioma" not in reuse_detected_language(df, pd.DataFrame(), "overview", "idioma").columns

    def test_ignora_schema_antigo_sem_coluna_de_idioma(self):
        df = pd.DataFrame({"id": [1], "overview": ["A"]})
        anterior = pd.DataFrame({"id": [1], "overview": ["A"]})
        result = reuse_detected_language(df, anterior, "overview", "idioma")
        assert "idioma" not in result.columns

    def test_ids_duplicados_no_df_anterior_usa_ultimo(self):
        df = pd.DataFrame({"id": [1], "overview": ["A"]})
        anterior = pd.DataFrame({"id": [1, 1], "overview": ["A", "A"], "idioma": ["en", "pt"]})
        result = reuse_detected_language(df, anterior, "overview", "idioma")
        assert result["idioma"].tolist() == ["pt"]

    def test_coluna_chave_customizada(self):
        df = pd.DataFrame({"iso_639_1": ["en"], "english_name": ["English"]})
        anterior = pd.DataFrame({"iso_639_1": ["en"], "english_name": ["English"], "idioma": ["en"]})
        result = reuse_detected_language(df, anterior, "english_name", "idioma", key_column="iso_639_1")
        assert result["idioma"].tolist() == ["en"]

    def test_loga_quantidade_reaproveitada(self, caplog):
        df = pd.DataFrame({"id": [1, 2], "overview": ["A", "B"]})
        anterior = pd.DataFrame({"id": [1, 2], "overview": ["A", "B"], "idioma": ["pt", "en"]})
        with caplog.at_level(logging.INFO):
            reuse_detected_language(df, anterior, "overview", "idioma")
        assert "Reaproveitando idioma detectado de 2 registro(s)" in caplog.text


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


class TestReuseExistingTranslationIdiomas:
    def _previous(self):
        return pd.DataFrame({
            "id": [1],
            "overview_en": ["Synopsis"],
            "overview_pt": ["Sinopse"],
            "idioma_en": ["en"],
            "idioma_pt": ["pt"],
        })

    def test_reaproveita_idiomas_junto_com_a_traducao(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Synopsis"], "overview_pt": [None]})
        result = reuse_existing_translation(
            df, self._previous(), "overview_en", "overview_pt",
            detected_language_en_column="idioma_en", detected_language_pt_column="idioma_pt",
        )
        assert result["overview_pt"].tolist() == ["Sinopse"]
        assert result["idioma_en"].tolist() == ["en"]
        assert result["idioma_pt"].tolist() == ["pt"]

    def test_idioma_pt_nao_reaproveitado_quando_o_destino_atual_difere_do_antigo(self):
        """Ex.: tradução nativa do TMDB (já atribuída pelo chamador) diferente da traduzida antes —
        o idioma antigo descreve outro texto, então a coluna fica pendente para ser detectada."""
        df = pd.DataFrame({"id": [1], "overview_en": ["Synopsis"], "overview_pt": ["Resumo nativo"]})
        result = reuse_existing_translation(
            df, self._previous(), "overview_en", "overview_pt",
            detected_language_en_column="idioma_en", detected_language_pt_column="idioma_pt",
        )
        assert result["overview_pt"].tolist() == ["Resumo nativo"]
        assert result["idioma_en"].tolist() == ["en"]
        assert result["idioma_pt"].isna().all()

    def test_idioma_en_nao_reaproveitado_quando_fonte_mudou(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["New synopsis"], "overview_pt": [None]})
        result = reuse_existing_translation(
            df, self._previous(), "overview_en", "overview_pt",
            detected_language_en_column="idioma_en", detected_language_pt_column="idioma_pt",
        )
        assert result["idioma_en"].isna().all()
        assert result["idioma_pt"].isna().all()

    def test_sem_colunas_de_idioma_informadas_nao_cria_colunas_de_idioma(self):
        df = pd.DataFrame({"id": [1], "overview_en": ["Synopsis"], "overview_pt": [None]})
        result = reuse_existing_translation(df, self._previous(), "overview_en", "overview_pt")
        assert "idioma_en" not in result.columns
        assert "idioma_pt" not in result.columns


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

    def test_detecta_idioma_em_paralelo_com_max_workers_informado(self):
        df = pd.DataFrame({"overview_en": ["Hello"], "overview_pt": [None]})
        with patch("shared_utils.traducao.detect_in_parallel") as mock_detectar:
            mock_detectar.side_effect = lambda textos, *a, **kw: ["en"] * len(textos)
            resolve_pt_translation(
                df, "overview_en", "overview_pt", "overview_idioma_en", "overview_idioma_pt",
                "overview_tentativas", lambda t: "en", lambda t: "Olá", max_workers=3,
            )
        assert mock_detectar.call_count == 3  # fonte, destino inicial e redetecção do traduzido
        assert all(c.kwargs["max_workers"] == 3 for c in mock_detectar.call_args_list)

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
