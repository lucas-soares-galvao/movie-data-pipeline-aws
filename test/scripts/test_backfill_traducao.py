"""
Testa scripts/backfill_traducao.py com awswrangler, translate_text_llm e boto3
mockados (nenhuma chamada real à AWS ou ao LLM via OpenRouter).

Foco: as funções puras (_add_translations_pt, _backfill_year) isoladamente,
e a orquestração de main() via mocks dessas funções — evita montar DataFrames
grandes só para testar o loop de anos.
Retry/backoff da tradução em si é coberto em test/shared_src/test_traducao.py.
"""

import json
from unittest.mock import MagicMock, patch

import backfill_traducao as bt
import pandas as pd
import pytest
from botocore.exceptions import ClientError

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "TABLE_GROUP": "traducao",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "S3_BUCKET_TEMP": "bucket-temp-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_DETAILS_MOVIE": "details_movie",
    "TABLE_DETAILS_TV": "details_tv",
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "S3_BUCKET_SPEC": "bucket-spec-test",
    "S3_PREFIX_SPEC": "tmdb",
    "DB_UNIFIED": "db_unified",
    "TABLE_DISCOVER_UNIFIED": "tb_discover_unified",
    "ENVIRONMENT": "dev",
}


ERRO_LEGADO = "Error 500 (Server Error)!!1500.That’s an error."


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> None:
    for key, value in {**ENV_BASE, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


def _s3_client_sem_checkpoint() -> MagicMock:
    """Cliente S3 mockado simulando ausência de checkpoint (comportamento padrão nos testes)."""
    client = MagicMock()
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject",
    )
    return client


class TestAdicionarTraducoesPt:
    def test_todos_overview_en_vazios_nao_chama_traducao(self):
        df = pd.DataFrame({"overview_en": ["", None]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, sucesso = bt._add_translations_pt(df, detect_fn=lambda t: None)
        mock_translate.assert_not_called()
        assert resultado["overview_pt"].isna().all()
        assert sucesso == 0
        assert resultado["overview_detected_language_pt"].isna().all()

    def test_traduz_independente_do_idioma_original(self):
        """original_language não é critério de elegibilidade (ver
        shared_utils.traducao.resolve_pt_translation) — todo registro com
        overview_en preenchido é traduzido, inclusive quando original_language == 'pt'."""
        df = pd.DataFrame({
            "original_language": ["en", "es", "pt"],
            "overview_en": ["Overview", "Resumen", "Sinopse"],
        })
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT"):
            resultado, sucesso = bt._add_translations_pt(df, detect_fn=lambda t: "en")

        assert resultado.loc[0, "overview_pt"] == "Overview_PT"
        assert resultado.loc[1, "overview_pt"] == "Resumen_PT"
        assert resultado.loc[2, "overview_pt"] == "Sinopse_PT"
        assert sucesso == 3

    def test_nao_conta_como_sucesso_quando_traducao_falha_e_mantem_original(self):
        """translate_text devolve o texto original quando falha após todas as tentativas."""
        df = pd.DataFrame({"overview_en": ["Overview", "Falhou"]})
        def detect_fn(t):
            return "pt" if t.endswith("_PT") else "en"
        with patch(
            "backfill_traducao.translate_text_llm",
            side_effect=lambda t: "Overview_PT" if t == "Overview" else t,
        ):
            resultado, sucesso = bt._add_translations_pt(df, detect_fn=detect_fn)

        assert resultado.loc[0, "overview_pt"] == "Overview_PT"
        assert resultado.loc[1, "overview_pt"] == "Falhou"
        assert sucesso == 1
        assert resultado.loc[0, "overview_detected_language_pt"] == "pt"
        assert resultado.loc[1, "overview_detected_language_pt"] != "pt"

    def test_pula_registros_ja_traduzidos_com_sucesso(self):
        """overview_pt já preenchido e cujo idioma detectado já é pt não é retraduzido."""
        df = pd.DataFrame({
            "overview_en": ["Já traduzido antes", "Ainda pendente"],
            "overview_pt": ["Already translated before", None],
        })
        def detect_fn(t):
            return "pt" if t == "Already translated before" else "en"
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._add_translations_pt(df, detect_fn=detect_fn)

        mock_translate.assert_called_once_with("Ainda pendente")
        assert resultado.loc[0, "overview_pt"] == "Already translated before"
        assert resultado.loc[1, "overview_pt"] == "Ainda pendente_PT"
        assert sucesso == 1

    def test_retenta_registro_cujo_overview_pt_ficou_igual_ao_original(self):
        """overview_pt == overview_en indica fallback de uma falha anterior — deve ser re-tentado."""
        df = pd.DataFrame({
            "overview_en": ["Falhou antes"],
            "overview_pt": ["Falhou antes"],
        })
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._add_translations_pt(df, detect_fn=lambda t: "en")

        mock_translate.assert_called_once_with("Falhou antes")
        assert resultado.loc[0, "overview_pt"] == "Falhou antes_PT"
        assert sucesso == 1

    def test_ignora_registros_com_overview_en_vazio(self):
        """overview_en vazio/None não tem o que traduzir — não entra na contagem
        de elegíveis (distorceria o "X de Y traduzidos com sucesso" do log)."""
        df = pd.DataFrame({"overview_en": ["Overview", "", None]})
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._add_translations_pt(df, detect_fn=lambda t: "en" if t else None)

        mock_translate.assert_called_once_with("Overview")
        assert sucesso == 1

    def test_todos_ja_traduzidos_nao_chama_traducao(self):
        df = pd.DataFrame({
            "overview_en": ["A", "B"],
            "overview_pt": ["A_PT", "B_PT"],
        })
        def detect_fn(t):
            return "pt" if t.endswith("_PT") else "en"
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, sucesso = bt._add_translations_pt(df, detect_fn=detect_fn)

        mock_translate.assert_not_called()
        assert resultado.loc[0, "overview_pt"] == "A_PT"
        assert resultado.loc[1, "overview_pt"] == "B_PT"
        assert sucesso == 0

    def test_idioma_detectado_en_calculado_a_partir_da_fonte(self):
        df = pd.DataFrame({"overview_en": ["Overview"]})
        detect_fn = MagicMock(side_effect=lambda t: "en" if t == "Overview" else None)
        resultado, _ = bt._add_translations_pt(df, detect_fn=lambda t: detect_fn(t))
        assert resultado["overview_detected_language_en"].iloc[0] == "en"
        detect_fn.assert_any_call("Overview")

    def test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao(self):
        """Otimização: fonte já detectada como pt-BR é copiada direto, sem chamar
        tradução — evita retradução infinita de texto que já está correto."""
        df = pd.DataFrame({"overview_en": ["Já em português"]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, sucesso = bt._add_translations_pt(df, detect_fn=lambda t: "pt")
        mock_translate.assert_not_called()
        assert resultado["overview_pt"].iloc[0] == "Já em português"
        assert sucesso == 0
        assert resultado["overview_detected_language_pt"].iloc[0] == "pt"

    def test_overview_precisa_traducao_true_quando_traducao_falha(self):
        df = pd.DataFrame({"overview_en": ["Falhou"]})
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: t):
            resultado, _ = bt._add_translations_pt(df, detect_fn=lambda t: "en" if t else None)
        assert bool(resultado["overview_needs_translation"].iloc[0]) is True

    def test_overview_precisa_traducao_false_quando_ja_em_portugues(self):
        df = pd.DataFrame({"overview_en": ["Já em português"]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, _ = bt._add_translations_pt(df, detect_fn=lambda t: "pt")
        mock_translate.assert_not_called()
        assert bool(resultado["overview_needs_translation"].iloc[0]) is False


class TestAdicionarTraducoesTaglinePt:
    def test_sem_tagline_nao_chama_traducao(self):
        df = pd.DataFrame({"tagline": [None, ""]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, sucesso = bt._add_translations_tagline_pt(df, detect_fn=lambda t: "en")
        mock_translate.assert_not_called()
        assert sucesso == 0

    def test_traduz_independente_do_idioma_original(self):
        df = pd.DataFrame({
            "original_language": ["en", "es", "pt"],
            "tagline": ["A phrase.", "Otra frase.", "Uma frase."],
        })
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._add_translations_tagline_pt(df, detect_fn=lambda t: "en")

        assert mock_translate.call_count == 3
        assert resultado.loc[0, "tagline_pt"] == "A phrase._PT"
        assert resultado.loc[2, "tagline_pt"] == "Uma frase._PT"
        assert sucesso == 3

    def test_pula_registros_ja_traduzidos(self):
        df = pd.DataFrame({
            "tagline": ["Já traduzida", "Pendente"],
            "tagline_pt": ["Already translated", None],
        })
        def detect_fn(t):
            return "pt" if t == "Already translated" else "en"
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._add_translations_tagline_pt(df, detect_fn=detect_fn)

        mock_translate.assert_called_once_with("Pendente")
        assert resultado.loc[0, "tagline_pt"] == "Already translated"
        assert resultado.loc[1, "tagline_pt"] == "Pendente_PT"
        assert sucesso == 1

    def test_retenta_registro_cujo_tagline_pt_ficou_igual_ao_original(self):
        df = pd.DataFrame({
            "tagline": ["Falhou antes"],
            "tagline_pt": ["Falhou antes"],
        })
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._add_translations_tagline_pt(df, detect_fn=lambda t: "en")

        mock_translate.assert_called_once_with("Falhou antes")
        assert resultado.loc[0, "tagline_pt"] == "Falhou antes_PT"
        assert sucesso == 1

    def test_guard_de_schema_legado_nao_cria_colunas_novas(self):
        """Partições antigas sem a coluna tagline não devem ganhar as colunas
        novas pela metade — mesmo guard de _add_translations_tagline_pt já
        existente (return df, 0 antecipado)."""
        df = pd.DataFrame({"overview_en": ["Overview"]})
        resultado, sucesso = bt._add_translations_tagline_pt(df, detect_fn=lambda t: "en")
        assert "tagline_detected_language_en" not in resultado.columns
        assert "tagline_detected_language_pt" not in resultado.columns
        assert "tagline_translation_attempts" not in resultado.columns
        assert "tagline_needs_translation" not in resultado.columns
        assert sucesso == 0

    def test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao(self):
        df = pd.DataFrame({"tagline": ["Já em português"]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, sucesso = bt._add_translations_tagline_pt(df, detect_fn=lambda t: "pt")
        mock_translate.assert_not_called()
        assert resultado["tagline_pt"].iloc[0] == "Já em português"
        assert sucesso == 0
        assert resultado["tagline_detected_language_pt"].iloc[0] == "pt"

    def test_tagline_precisa_traducao_true_quando_traducao_falha(self):
        df = pd.DataFrame({"tagline": ["Falhou antes"], "tagline_pt": ["Falhou antes"]})
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: t):
            resultado, _ = bt._add_translations_tagline_pt(df, detect_fn=lambda t: "en")
        assert bool(resultado["tagline_needs_translation"].iloc[0]) is True

    def test_tagline_precisa_traducao_false_quando_ja_em_portugues(self):
        df = pd.DataFrame({"tagline": ["Já em português"]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, _ = bt._add_translations_tagline_pt(df, detect_fn=lambda t: "pt")
        mock_translate.assert_not_called()
        assert bool(resultado["tagline_needs_translation"].iloc[0]) is False


class TestAdicionarTraducoesKeywordsPt:
    def test_sem_keywords_nao_chama_traducao(self):
        df = pd.DataFrame({"keywords": [None, ""]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, sucesso = bt._add_translations_keywords_pt(df, detect_fn=lambda t: None)
        mock_translate.assert_not_called()
        assert sucesso == 0

    def test_traduz_independente_do_idioma_original(self):
        """Keywords não são localizadas pela API do TMDB — continuam em inglês
        mesmo quando original_language == 'pt', por isso original_language não
        é critério de elegibilidade (ver shared_utils.traducao.resolve_pt_translation)."""
        df = pd.DataFrame({
            "original_language": ["en", "pt"],
            "keywords": ["space, alien", "action, drama"],
        })
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._add_translations_keywords_pt(df, detect_fn=lambda t: "en")

        assert mock_translate.call_count == 2
        assert resultado.loc[0, "keywords_pt"] == "space, alien_PT"
        assert resultado.loc[1, "keywords_pt"] == "action, drama_PT"
        assert sucesso == 2

    def test_pula_registros_ja_traduzidos(self):
        df = pd.DataFrame({
            "keywords": ["já traduzida", "pendente"],
            "keywords_pt": ["already translated", None],
        })
        def detect_fn(t):
            return "pt" if t == "already translated" else "en"
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._add_translations_keywords_pt(df, detect_fn=detect_fn)

        mock_translate.assert_called_once_with("pendente")
        assert resultado.loc[0, "keywords_pt"] == "already translated"
        assert resultado.loc[1, "keywords_pt"] == "pendente_PT"
        assert sucesso == 1

    def test_guard_de_schema_legado_nao_cria_colunas_novas(self):
        df = pd.DataFrame({"overview_en": ["Overview"]})
        resultado, sucesso = bt._add_translations_keywords_pt(df, detect_fn=lambda t: "en")
        assert "keywords_detected_language_en" not in resultado.columns
        assert "keywords_detected_language_pt" not in resultado.columns
        assert "keywords_translation_attempts" not in resultado.columns
        assert "keywords_needs_translation" not in resultado.columns
        assert sucesso == 0

    def test_copia_direta_quando_fonte_ja_detectada_como_pt_sem_chamar_traducao(self):
        df = pd.DataFrame({"keywords": ["ação, suspense"]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, sucesso = bt._add_translations_keywords_pt(df, detect_fn=lambda t: "pt")
        mock_translate.assert_not_called()
        assert resultado["keywords_pt"].iloc[0] == "ação, suspense"
        assert sucesso == 0
        assert resultado["keywords_detected_language_pt"].iloc[0] == "pt"

    def test_keywords_precisa_traducao_true_quando_traducao_falha(self):
        df = pd.DataFrame({"keywords": ["action, drama"]})
        with patch("backfill_traducao.translate_text_llm", side_effect=lambda t: t):
            resultado, _ = bt._add_translations_keywords_pt(df, detect_fn=lambda t: "en")
        assert bool(resultado["keywords_needs_translation"].iloc[0]) is True

    def test_keywords_precisa_traducao_false_quando_ja_em_portugues(self):
        df = pd.DataFrame({"keywords": ["ação, suspense"]})
        with patch("backfill_traducao.translate_text_llm") as mock_translate:
            resultado, _ = bt._add_translations_keywords_pt(df, detect_fn=lambda t: "pt")
        mock_translate.assert_not_called()
        assert bool(resultado["keywords_needs_translation"].iloc[0]) is False


class TestBackfillYear:
    def test_sem_arquivos_retorna_false_e_nao_escreve(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = Exception("NoFilesFound: nada aqui")
            resultado, traduzidos = bt._backfill_year("db_movie", "details_movie", "2020", "bucket-sot-test")

        assert resultado is False
        assert traduzidos == 0
        mock_wr.s3.to_parquet.assert_not_called()

    def test_df_vazio_retorna_false_e_nao_escreve(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = pd.DataFrame()
            resultado, traduzidos = bt._backfill_year("db_movie", "details_movie", "2020", "bucket-sot-test")

        assert resultado is False
        assert traduzidos == 0
        mock_wr.s3.to_parquet.assert_not_called()

    def test_outras_excecoes_sao_repropagadas(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = RuntimeError("acesso negado")
            with pytest.raises(RuntimeError, match="acesso negado"):
                bt._backfill_year("db_movie", "details_movie", "2020", "bucket-sot-test")

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_na_leitura_loga_e_repropaga(self, caplog, codigo):
        """Reproduz o erro real de produção: ListObjectsV2 (via wr.s3.read_parquet) retorna
        o código S3 'ExpiredToken', não o código STS 'ExpiredTokenException'."""
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = ClientError(
                {"Error": {"Code": codigo, "Message": "expired"}}, "GetObject",
            )
            with caplog.at_level("ERROR", logger="backfill_traducao"):
                with pytest.raises(ClientError):
                    bt._backfill_year("db_movie", "details_movie", "2020", "bucket-sot-test")
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_na_escrita_loga_e_repropaga(self, caplog, codigo):
        details_df = pd.DataFrame({"id": [1], "overview_en": ["a"]})

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            mock_wr.s3.to_parquet.side_effect = ClientError(
                {"Error": {"Code": codigo, "Message": "expired"}}, "PutObject",
            )
            with caplog.at_level("ERROR", logger="backfill_traducao"):
                with pytest.raises(ClientError):
                    bt._backfill_year("db_movie", "details_movie", "2020", "bucket-sot-test")
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    def test_escreve_com_particao_e_modo_overwrite_partitions(self):
        details_df = pd.DataFrame({
            "id": [1, 2],
            "overview_en": ["a", "b"],
        })

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            resultado, traduzidos = bt._backfill_year("db_movie", "details_movie", "2020", "bucket-sot-test")

        assert resultado is True
        assert traduzidos == 2
        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert kwargs["path"] == "s3://bucket-sot-test/tmdb/details_movie/"
        assert kwargs["partition_cols"] == ["year"]
        assert kwargs["mode"] == "overwrite_partitions"
        assert kwargs["database"] == "db_movie"
        assert kwargs["table"] == "details_movie"
        assert (kwargs["df"]["year"] == "2020").all()

    def test_soma_traduzidos_de_overview_tagline_e_keywords(self):
        """traduzidos retornado por _backfill_year é a soma dos três campos, não só overview_pt."""
        details_df = pd.DataFrame({
            "id": [1],
            "overview_en": ["Overview"],
            "tagline": ["Tagline"],
            "keywords": ["space, alien"],
        })

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            resultado, traduzidos = bt._backfill_year("db_movie", "details_movie", "2020", "bucket-sot-test")

        assert resultado is True
        assert traduzidos == 3  # 1 overview_pt + 1 tagline_pt + 1 keywords_pt
        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        df_escrito = kwargs["df"]
        assert df_escrito.loc[0, "overview_pt"] == "Overview_PT"
        assert df_escrito.loc[0, "tagline_pt"] == "Tagline_PT"
        assert df_escrito.loc[0, "keywords_pt"] == "space, alien_PT"

    def test_reset_polluted_retraduz_pagina_de_erro_mesmo_com_tentativas_esgotadas(self):
        """Com reset_polluted=True, o texto de erro legado é descartado e o contador
        zerado, então a linha é retraduzida pelo LLM mesmo tendo esgotado o teto."""
        details_df = pd.DataFrame({
            "id": [1],
            "overview_en": ["Overview"],
            "overview_pt": [ERRO_LEGADO],
            "overview_translation_attempts": [3],
        })

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao.translate_text_llm", side_effect=lambda t: f"{t}_PT") as mock_translate,
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            bt._backfill_year(
                "db_movie", "details_movie", "2020", "bucket-sot-test",
                detect_fn=lambda t: "pt" if t.endswith("_PT") else "en",
                reset_polluted=True,
            )

        mock_translate.assert_called_once_with("Overview")
        df_escrito = mock_wr.s3.to_parquet.call_args.kwargs["df"]
        assert df_escrito.loc[0, "overview_pt"] == "Overview_PT"
        assert df_escrito.loc[0, "overview_translation_attempts"] == 1

    def test_sem_reset_polluted_respeita_o_teto_de_tentativas(self):
        """Comportamento padrão (reset desligado): _reset_polluted_translations não roda e
        a linha que já esgotou o teto de tentativas não é retraduzida."""
        details_df = pd.DataFrame({
            "id": [1],
            "overview_en": ["Overview"],
            "overview_pt": [ERRO_LEGADO],
            "overview_translation_attempts": [3],
        })

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao.translate_text_llm") as mock_translate,
            patch("backfill_traducao._reset_polluted_translations") as mock_reset,
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            bt._backfill_year(
                "db_movie", "details_movie", "2020", "bucket-sot-test",
                detect_fn=lambda t: "en",
            )

        mock_reset.assert_not_called()
        mock_translate.assert_not_called()


class TestResetPollutedTranslations:
    def test_descarta_so_a_pagina_de_erro_e_zera_idioma_e_tentativas(self):
        df = pd.DataFrame({
            "overview_pt": [ERRO_LEGADO, "Tradução boa", None],
            "overview_detected_language_pt": ["en", "pt", None],
            "overview_translation_attempts": [3, 1, 0],
        })

        descartados = bt._reset_polluted_translations(df)

        assert descartados == 1
        assert pd.isna(df.loc[0, "overview_pt"])
        assert pd.isna(df.loc[0, "overview_detected_language_pt"])
        assert df.loc[0, "overview_translation_attempts"] == 0
        assert df.loc[1, "overview_pt"] == "Tradução boa"
        assert df.loc[1, "overview_detected_language_pt"] == "pt"
        assert df.loc[1, "overview_translation_attempts"] == 1

    def test_nao_casa_com_traducao_que_apenas_menciona_error(self):
        df = pd.DataFrame({"overview_pt": ["Mensagem: Error 500 (Server Error)!!1 no meio"]})
        assert bt._reset_polluted_translations(df) == 0
        assert df.loc[0, "overview_pt"] == "Mensagem: Error 500 (Server Error)!!1 no meio"

    def test_soma_os_tres_campos_e_ignora_coluna_ausente(self):
        df = pd.DataFrame({
            "overview_pt": [ERRO_LEGADO],
            "tagline_pt": [ERRO_LEGADO],
            # keywords_pt ausente: não deve quebrar
        })
        assert bt._reset_polluted_translations(df) == 2


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict | None = None,
    mock_s3: MagicMock | None = None,
    notify_capture: list | None = None,
):
    """notify_capture (se passado) recebe o mock de shared.notify_backfill_success — não muda
    a tupla de mocks já retornada por esta função (consumida por unpacking fixo em quase todo
    teste existente)."""
    _set_env(monkeypatch, overrides)
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()
    with (
        patch("backfill_traducao._backfill_year") as mock_backfill,
        patch("backfill_traducao.time.sleep") as mock_sleep,
        patch("backfill_traducao.boto3") as mock_boto3,
        patch("backfill_traducao.shared.trigger_agg_locally") as mock_agg,
        patch("backfill_traducao.shared.notify_backfill_success") as mock_notify,
    ):
        mock_backfill.return_value = (True, 1)  # translated_count > 0: comportamento padrão de pausa entre partições
        mock_boto3.client.return_value = mock_s3
        bt.main()
        if notify_capture is not None:
            notify_capture.append(mock_notify)
    return mock_backfill, mock_sleep, mock_s3, mock_agg


class TestMain:
    def test_backfill_year_chamado_para_cada_ano_e_tipo(self, monkeypatch):
        mock_backfill, _, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_backfill.call_count == 6  # 3 anos x 2 tipos

    @pytest.mark.parametrize("valor, esperado", [(None, False), ("true", True), ("TRUE", True), ("false", False)])
    def test_reset_polluted_vem_de_backfill_reset_attempts(self, monkeypatch, valor, esperado):
        overrides = {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}
        if valor is None:
            monkeypatch.delenv("BACKFILL_RESET_ATTEMPTS", raising=False)
        else:
            overrides["BACKFILL_RESET_ATTEMPTS"] = valor
        mock_backfill, _, _, _ = _run_main(monkeypatch, overrides)
        assert all(c.kwargs["reset_polluted"] is esperado for c in mock_backfill.call_args_list)

    def test_alterna_movie_e_tv_por_ano(self, monkeypatch):
        mock_backfill, _, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        databases = [c.kwargs["database"] for c in mock_backfill.call_args_list]
        assert databases == ["db_movie", "db_tv"]

    def test_nao_pausa_apos_ultima_chamada(self, monkeypatch):
        mock_backfill, mock_sleep, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_sleep.call_count == mock_backfill.call_count - 1

    def test_nao_pausa_quando_particao_nao_traduziu_nada(self, monkeypatch):
        """Partição vazia/já 100% traduzida (translated_count == 0) não tem chamada de
        API alguma para "esfriar" — pausar mesmo assim só desperdiça tempo de wall-clock
        num backfill de anos antigos ou de range grande."""
        with (
            patch("backfill_traducao._backfill_year") as mock_backfill,
            patch("backfill_traducao.time.sleep") as mock_sleep,
            patch("backfill_traducao.boto3") as mock_boto3,
            patch("backfill_traducao.shared.trigger_agg_locally"),
        ):
            _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
            mock_backfill.return_value = (False, 0)
            mock_boto3.client.return_value = _s3_client_sem_checkpoint()
            bt.main()

        mock_sleep.assert_not_called()

    def test_pausa_apenas_apos_particoes_que_traduziram_algo(self, monkeypatch):
        """Mistura de partições com e sem tradução: só pausa depois das que traduziram
        (e nunca depois da última, independente de ter traduzido ou não)."""
        with (
            patch("backfill_traducao._backfill_year") as mock_backfill,
            patch("backfill_traducao.time.sleep") as mock_sleep,
            patch("backfill_traducao.boto3") as mock_boto3,
            patch("backfill_traducao.shared.trigger_agg_locally"),
        ):
            _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
            # movie:2020 traduz, tv:2020 vazio, movie:2021 traduz, tv:2021 (última) traduz
            mock_backfill.side_effect = [(True, 3), (False, 0), (True, 2), (True, 1)]
            mock_boto3.client.return_value = _s3_client_sem_checkpoint()
            bt.main()

        assert mock_sleep.call_count == 2  # após movie:2020 e após movie:2021 — não após tv:2020 nem após a última

    def test_loga_total_de_traduzidos_com_sucesso_acumulado(self, monkeypatch, caplog):
        """O total no log final soma os traduzidos com sucesso de cada partição, não a quantidade de partições."""
        with (
            patch("backfill_traducao._backfill_year") as mock_backfill,
            patch("backfill_traducao.time.sleep"),
            patch("backfill_traducao.boto3") as mock_boto3,
            patch("backfill_traducao.shared.trigger_agg_locally"),
        ):
            _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
            mock_backfill.side_effect = [(True, 7), (False, 0)]  # movie:2020 traduz 7, tv:2020 sem dados
            mock_boto3.client.return_value = _s3_client_sem_checkpoint()

            with caplog.at_level("INFO"):
                bt.main()

        resumo = [r.message for r in caplog.records if "Backfill de tradução concluído" in r.message]
        assert len(resumo) == 1
        assert "7 campos traduzidos com sucesso" in resumo[0]


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("S3_BUCKET_SOT", raising=False)
        with pytest.raises(EnvironmentError):
            bt.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetObject")
        assert bt.shared.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "GetObject")
        assert bt.shared.expired_token_exit_code(exc) == 75


class TestCheckpoint:
    def test_pula_particoes_ja_concluidas(self, monkeypatch):
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=json.dumps(
                {"start_year": 2020, "end_year": 2021, "completed": ["movie:2020", "tv:2020"]}
            ).encode()))
        }

        mock_backfill, _, _, _ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"}, mock_s3=mock_s3,
        )

        anos = [(c.kwargs["database"], c.kwargs["year"]) for c in mock_backfill.call_args_list]
        assert anos == [("db_movie", "2021"), ("db_tv", "2021")]

    def test_salva_checkpoint_apos_cada_particao(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        assert mock_s3.put_object.call_count == 2  # movie:2020, tv:2020

    def test_marca_completo_mesmo_quando_backfill_year_retorna_false(self, monkeypatch):
        """Nenhum arquivo/registro para a partição ainda conta como concluído (nada para fazer, não é falha)."""
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3,
        )

        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["movie:2020", "tv:2020"]

    def test_limpa_checkpoint_ao_concluir_tudo_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        mock_s3.delete_object.assert_called_once()

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_checkpoint_reflete_progresso_parcial_quando_interrompido(self, monkeypatch, codigo):
        _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        mock_s3 = _s3_client_sem_checkpoint()

        with (
            patch("backfill_traducao._backfill_year") as mock_backfill,
            patch("backfill_traducao.time.sleep"),
            patch("backfill_traducao.boto3") as mock_boto3,
        ):
            mock_boto3.client.return_value = mock_s3
            mock_backfill.side_effect = [
                (True, 3),
                ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "GetObject"),
            ]
            with pytest.raises(ClientError):
                bt.main()

        assert mock_s3.put_object.call_count == 1
        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["movie:2020"]


class TestGlueAgg:
    def test_chamado_antes_de_clear_checkpoint(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        call_order: list = []
        mock_s3.delete_object.side_effect = lambda *a, **k: call_order.append("clear_checkpoint")

        with (
            patch("backfill_traducao._backfill_year", return_value=(True, 1)),
            patch("backfill_traducao.time.sleep"),
            patch("backfill_traducao.boto3") as mock_boto3,
            patch("backfill_traducao.shared.trigger_agg_locally") as mock_agg,
        ):
            _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
            mock_agg.side_effect = lambda *a, **k: call_order.append("trigger_agg_locally")
            mock_boto3.client.return_value = mock_s3
            bt.main()

        assert call_order == ["trigger_agg_locally", "clear_checkpoint"]
        mock_agg.assert_called_once_with(
            s3_bucket_spec="bucket-spec-test",
            s3_prefix_spec="tmdb",
            s3_bucket_temp="bucket-temp-test",
            db_movie="db_movie",
            db_tv="db_tv",
            db_unified="db_unified",
            table_name="tb_discover_unified",
            dq_job_name="dq-job",
            environment="dev",
        )


class TestNotificacaoSucesso:
    def test_chamado_ao_final_de_um_main_bem_sucedido(self, monkeypatch):
        notify_capture: list = []

        _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, notify_capture=notify_capture,
        )

        mock_notify = notify_capture[0]
        mock_notify.assert_called_once_with(
            "traducao",
            "Backfill de tradução concluído: 2020 até 2020 | 2 campos traduzidos com sucesso "
            "(overview_pt + tagline_pt + keywords_pt)",
        )
