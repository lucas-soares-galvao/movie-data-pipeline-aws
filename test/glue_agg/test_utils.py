"""Testes unitarios para app/glue_agg/src/utils.py."""

from unittest.mock import MagicMock, patch

import pandas as pd

from src.utils import run_athena_query, traduzir_colunas_en


class TestRunAthenaQuery:
    def test_passes_sql_with_image_columns_to_wrangler(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(database="db_tmdb", s3_bucket_temp="my-temp")

            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "AS poster_url" in sql
            assert "AS backdrop_url" in sql
            assert "https://image.tmdb.org/t/p/w342" in sql
            assert "https://image.tmdb.org/t/p/w780" in sql
            assert "tb_discover_movie_tmdb" in sql
            assert "tb_discover_tv_tmdb" in sql
            assert "overview" in sql
            assert "air_date" in sql
            assert "origin_country_name" in sql
            assert "language_name" in sql

    def test_uses_expected_wrangler_execution_args(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(database="db_tmdb", s3_bucket_temp="my-temp")

            mock_read.assert_called_once()
            _, kwargs = mock_read.call_args
            assert kwargs["database"] == "db_tmdb"
            assert kwargs["s3_output"] == "s3://my-temp/athena/glue_agg/"
            assert kwargs["ctas_approach"] is True

    def test_query_contains_details_movie_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(database="db_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_details_movie_tmdb" in sql
            assert "runtime_minutes" in sql

    def test_query_contains_details_tv_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(database="db_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_details_tv_tmdb" in sql
            assert "number_of_seasons" in sql
            assert "number_of_episodes" in sql
            assert "episode_runtime_minutes" in sql

    def test_query_contains_watch_providers_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(database="db_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_watch_providers_movie_tmdb" in sql
            assert "tb_watch_providers_tv_tmdb" in sql
            assert "streaming_providers" in sql


class TestTraduzirColunasEn:
    def _make_df(self, rows):
        return pd.DataFrame(rows)

    def test_traduz_title_e_overview_quando_original_language_en(self):
        df = self._make_df([
            {"original_language": "en", "title": "The Matrix", "overview": "A hacker discovers reality."},
            {"original_language": "pt", "title": "Cidade de Deus", "overview": "Um jovem no Rio de Janeiro."},
        ])
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = lambda texto: f"[PT] {texto}"

        with patch("src.utils.GoogleTranslator", return_value=mock_translator):
            result = traduzir_colunas_en(df)

        assert result.loc[0, "title"] == "[PT] The Matrix"
        assert result.loc[0, "overview"] == "[PT] A hacker discovers reality."
        assert result.loc[1, "title"] == "Cidade de Deus"
        assert result.loc[1, "overview"] == "Um jovem no Rio de Janeiro."

    def test_retorna_df_inalterado_quando_sem_registros_en(self):
        df = self._make_df([
            {"original_language": "pt", "title": "Tropa de Elite", "overview": "Descricao."},
            {"original_language": "es", "title": "Roma", "overview": "Descripcion."},
        ])
        with patch("src.utils.GoogleTranslator") as mock_cls:
            result = traduzir_colunas_en(df)
            mock_cls.assert_not_called()

        pd.testing.assert_frame_equal(result, df)

    def test_nao_altera_original_title(self):
        df = self._make_df([
            {
                "original_language": "en",
                "title": "Inception",
                "original_title": "Inception",
                "overview": "A thief enters dreams.",
            }
        ])
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = lambda texto: f"[PT] {texto}"

        with patch("src.utils.GoogleTranslator", return_value=mock_translator):
            result = traduzir_colunas_en(df)

        assert result.loc[0, "original_title"] == "Inception"

    def test_fallback_mantém_texto_original_em_caso_de_erro(self):
        df = self._make_df([
            {"original_language": "en", "title": "Dune", "overview": "Desert planet."},
        ])
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("timeout")

        with patch("src.utils.GoogleTranslator", return_value=mock_translator):
            result = traduzir_colunas_en(df)

        assert result.loc[0, "title"] == "Dune"
        assert result.loc[0, "overview"] == "Desert planet."

    def test_overview_vazio_nao_chama_translate(self):
        df = self._make_df([
            {"original_language": "en", "title": "Unknown", "overview": ""},
        ])
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "algo"

        with patch("src.utils.GoogleTranslator", return_value=mock_translator):
            result = traduzir_colunas_en(df)

        assert result.loc[0, "overview"] == ""
