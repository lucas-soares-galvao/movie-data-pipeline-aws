"""
Testa scripts/backfill_traducao.py com awswrangler, GoogleTranslator e boto3
mockados (nenhuma chamada real à AWS ou ao Google Translate).

Foco: as funções puras (_translate, _adicionar_traducoes_pt, _backfill_year,
_load_discover_map) isoladamente, e a orquestração de main() via mocks dessas
funções — evita montar DataFrames grandes só para testar o loop de anos.
"""

from unittest.mock import patch

import pandas as pd
import pytest

import backfill_traducao as bt

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_DETAILS_MOVIE": "details_movie",
    "TABLE_DETAILS_TV": "details_tv",
    "TABLE_DISCOVER_MOVIE": "discover_movie",
    "TABLE_DISCOVER_TV": "discover_tv",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> None:
    for key, value in {**ENV_BASE, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


class TestTranslate:
    def test_string_vazia_retorna_vazia_sem_chamar_google(self):
        with patch("backfill_traducao.GoogleTranslator") as mock_google:
            assert bt._translate("") == ""
        mock_google.assert_not_called()

    def test_traduz_com_sucesso_na_primeira_tentativa(self):
        with patch("backfill_traducao.GoogleTranslator") as mock_google:
            mock_google.return_value.translate.return_value = "traduzido"
            assert bt._translate("hello") == "traduzido"
        assert mock_google.return_value.translate.call_count == 1

    def test_tenta_novamente_apos_excecao_e_depois_sucede(self):
        with (
            patch("backfill_traducao.GoogleTranslator") as mock_google,
            patch("backfill_traducao.time.sleep"),
        ):
            mock_google.return_value.translate.side_effect = [Exception("timeout"), "traduzido"]
            assert bt._translate("hello") == "traduzido"
        assert mock_google.return_value.translate.call_count == 2

    def test_retorna_texto_original_apos_tres_falhas(self):
        with (
            patch("backfill_traducao.GoogleTranslator") as mock_google,
            patch("backfill_traducao.time.sleep"),
        ):
            mock_google.return_value.translate.side_effect = Exception("timeout")
            assert bt._translate("hello") == "hello"
        assert mock_google.return_value.translate.call_count == 3


class TestAdicionarTraducoesPt:
    def test_sem_registros_en_nao_chama_traducao(self):
        df = pd.DataFrame({"original_language": ["pt", "es"], "title_en": ["a", "b"], "overview_en": ["c", "d"]})
        with patch("backfill_traducao._translate") as mock_translate:
            resultado = bt._adicionar_traducoes_pt(df)
        mock_translate.assert_not_called()
        assert resultado["title_pt"].isna().all()
        assert resultado["overview_pt"].isna().all()

    def test_traduz_apenas_registros_en(self):
        df = pd.DataFrame({
            "original_language": ["en", "pt"],
            "title_en": ["Movie", "Filme"],
            "overview_en": ["Overview", "Sinopse"],
        })
        with patch("backfill_traducao._translate", side_effect=lambda t: f"{t}_PT"):
            resultado = bt._adicionar_traducoes_pt(df)

        assert resultado.loc[0, "title_pt"] == "Movie_PT"
        assert resultado.loc[0, "overview_pt"] == "Overview_PT"
        assert pd.isna(resultado.loc[1, "title_pt"])
        assert pd.isna(resultado.loc[1, "overview_pt"])


class TestLoadDiscoverMap:
    def test_remove_duplicatas_e_seleciona_colunas(self):
        df_bruto = pd.DataFrame({
            "id": [1, 1, 2],
            "original_language": ["en", "en", "pt"],
            "coluna_extra": ["x", "y", "z"],
        })
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = df_bruto
            resultado = bt._load_discover_map("discover_movie", "bucket-sot-test")

        mock_wr.s3.read_parquet.assert_called_once_with(
            path="s3://bucket-sot-test/tmdb/discover_movie/", columns=["id", "original_language"],
        )
        assert list(resultado.columns) == ["id", "original_language"]
        assert len(resultado) == 2


class TestBackfillYear:
    def test_sem_arquivos_retorna_false_e_nao_escreve(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = Exception("NoFilesFound: nada aqui")
            resultado = bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

        assert resultado is False
        mock_wr.s3.to_parquet.assert_not_called()

    def test_df_vazio_retorna_false_e_nao_escreve(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = pd.DataFrame()
            resultado = bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

        assert resultado is False
        mock_wr.s3.to_parquet.assert_not_called()

    def test_outras_excecoes_sao_repropagadas(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = RuntimeError("acesso negado")
            with pytest.raises(RuntimeError, match="acesso negado"):
                bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

    def test_escreve_com_particao_e_modo_overwrite_partitions(self):
        details_df = pd.DataFrame({
            "id": [1, 2],
            "title_en": ["A", "B"],
            "overview_en": ["a", "b"],
        })
        discover_map = pd.DataFrame({"id": [1, 2], "original_language": ["en", None]})

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao._translate", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            resultado = bt._backfill_year("db_movie", "details_movie", discover_map, "2020", "bucket-sot-test")

        assert resultado is True
        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert kwargs["path"] == "s3://bucket-sot-test/tmdb/details_movie/"
        assert kwargs["partition_cols"] == ["year"]
        assert kwargs["mode"] == "overwrite_partitions"
        assert kwargs["database"] == "db_movie"
        assert kwargs["table"] == "details_movie"
        assert "original_language" not in kwargs["df"].columns
        assert (kwargs["df"]["year"] == "2020").all()


def _run_main(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None):
    _set_env(monkeypatch, overrides)
    with (
        patch("backfill_traducao._load_discover_map") as mock_load,
        patch("backfill_traducao._backfill_year") as mock_backfill,
        patch("backfill_traducao.time.sleep") as mock_sleep,
    ):
        mock_load.return_value = pd.DataFrame({"id": [], "original_language": []})
        bt.main()
    return mock_load, mock_backfill, mock_sleep


class TestMain:
    def test_carrega_discover_map_uma_vez_por_tipo(self, monkeypatch):
        mock_load, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_load.call_count == 2  # movie + tv, independente do numero de anos

    def test_backfill_year_chamado_para_cada_ano_e_tipo(self, monkeypatch):
        _, mock_backfill, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_backfill.call_count == 6  # 3 anos x 2 tipos

    def test_alterna_movie_e_tv_por_ano(self, monkeypatch):
        _, mock_backfill, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        databases = [c.kwargs["database"] for c in mock_backfill.call_args_list]
        assert databases == ["db_movie", "db_tv"]

    def test_nao_pausa_apos_ultima_chamada(self, monkeypatch):
        _, mock_backfill, mock_sleep = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_sleep.call_count == mock_backfill.call_count - 1


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("S3_BUCKET_SOT", raising=False)
        with pytest.raises(EnvironmentError):
            bt.main()
