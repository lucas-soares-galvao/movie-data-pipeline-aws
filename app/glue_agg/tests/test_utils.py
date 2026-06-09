"""Testes unitários para app/glue_agg/src/utils.py."""

from unittest.mock import MagicMock, patch

import pandas as pd

from app.glue_agg.src.utils import (
    _DISCOVER_UNIFIED_QUERY,
    run_athena_query,
    traduzir_colunas_en,
    write_parquet_to_spec,
)


# ---------------------------------------------------------------------------
# _DISCOVER_UNIFIED_QUERY (smoke tests da query template)
# ---------------------------------------------------------------------------

class TestDiscoverUnifiedQuery:
    def test_has_db_movie_placeholder(self):
        assert "{db_movie}" in _DISCOVER_UNIFIED_QUERY

    def test_has_db_tv_placeholder(self):
        assert "{db_tv}" in _DISCOVER_UNIFIED_QUERY

    def test_format_substitutes_placeholders(self):
        sql = _DISCOVER_UNIFIED_QUERY.format(db_movie="db_m", db_tv="db_t", db_unified="db_u")
        assert "db_m." in sql
        assert "db_t." in sql
        assert "{db_movie}" not in sql
        assert "{db_tv}" not in sql

    def test_query_has_union_all(self):
        assert "UNION ALL" in _DISCOVER_UNIFIED_QUERY

    def test_query_selects_media_type(self):
        assert "media_type" in _DISCOVER_UNIFIED_QUERY


# ---------------------------------------------------------------------------
# run_athena_query
# ---------------------------------------------------------------------------

class TestRunAthenaQuery:
    @patch("app.glue_agg.src.utils.wr")
    def test_calls_read_sql_query_with_ctas(self, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame([{"id": 1}])

        run_athena_query("db_movie", "db_tv", "db_unified", "my-temp-bucket")

        mock_wr.athena.read_sql_query.assert_called_once()
        call_kwargs = mock_wr.athena.read_sql_query.call_args.kwargs
        assert call_kwargs["ctas_approach"] is True
        assert call_kwargs["database"] == "db_unified"

    @patch("app.glue_agg.src.utils.wr")
    def test_s3_output_uses_temp_bucket(self, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame()

        run_athena_query("db_movie", "db_tv", "db_unified", "my-temp-bucket")

        call_kwargs = mock_wr.athena.read_sql_query.call_args.kwargs
        assert call_kwargs["s3_output"] == "s3://my-temp-bucket/athena/glue_agg/"

    @patch("app.glue_agg.src.utils.wr")
    def test_returns_dataframe(self, mock_wr):
        expected = pd.DataFrame([{"id": 1, "title": "Movie"}])
        mock_wr.athena.read_sql_query.return_value = expected

        result = run_athena_query("db_movie", "db_tv", "db_unified", "bucket")

        assert result is expected

    @patch("app.glue_agg.src.utils.wr")
    def test_sql_contains_resolved_databases(self, mock_wr):
        mock_wr.athena.read_sql_query.return_value = pd.DataFrame()

        run_athena_query("my_movie_db", "my_tv_db", "unified_db", "bucket")

        sql = mock_wr.athena.read_sql_query.call_args.kwargs["sql"]
        assert "my_movie_db." in sql
        assert "my_tv_db." in sql


# ---------------------------------------------------------------------------
# traduzir_colunas_en
# ---------------------------------------------------------------------------

class TestTraduzirColunasEn:
    def test_returns_unchanged_when_no_english_rows(self):
        df = pd.DataFrame([
            {"original_language": "pt", "title": "Filme", "overview": "Sinopse"},
        ])
        result = traduzir_colunas_en(df.copy())
        assert result["title"].iloc[0] == "Filme"

    @patch("app.glue_agg.src.utils.GoogleTranslator")
    def test_translates_title_and_overview_for_en_rows(self, mock_translator_cls):
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = lambda text: f"[PT]{text}"
        mock_translator_cls.return_value = mock_translator

        df = pd.DataFrame([
            {"original_language": "en", "title": "Movie", "overview": "Great film."},
            {"original_language": "pt", "title": "Filme", "overview": "Ótimo filme."},
        ])
        result = traduzir_colunas_en(df.copy())

        assert result.iloc[0]["title"] == "[PT]Movie"
        assert result.iloc[0]["overview"] == "[PT]Great film."
        # Linha em pt não deve ser alterada
        assert result.iloc[1]["title"] == "Filme"

    @patch("app.glue_agg.src.utils.GoogleTranslator")
    def test_handles_translation_failure_gracefully(self, mock_translator_cls):
        mock_translator = MagicMock()
        mock_translator.translate.side_effect = Exception("API timeout")
        mock_translator_cls.return_value = mock_translator

        df = pd.DataFrame([
            {"original_language": "en", "title": "Movie", "overview": "Overview"},
        ])
        result = traduzir_colunas_en(df.copy())

        # Em caso de falha, mantém o valor original
        assert result.iloc[0]["title"] == "Movie"
        assert result.iloc[0]["overview"] == "Overview"

    @patch("app.glue_agg.src.utils.GoogleTranslator")
    def test_empty_string_not_translated(self, mock_translator_cls):
        mock_translator = MagicMock()
        mock_translator.translate.return_value = "traduzido"
        mock_translator_cls.return_value = mock_translator

        df = pd.DataFrame([
            {"original_language": "en", "title": "", "overview": ""},
        ])
        result = traduzir_colunas_en(df.copy())

        # Strings vazias retornam "" sem chamar a API
        assert result.iloc[0]["title"] == ""
        assert result.iloc[0]["overview"] == ""


# ---------------------------------------------------------------------------
# write_parquet_to_spec
# ---------------------------------------------------------------------------

class TestWriteParquetToSpec:
    @patch("app.glue_agg.src.utils.wr")
    def test_calls_to_parquet_with_correct_path(self, mock_wr):
        df = pd.DataFrame([{"id": 1, "media_type": "movie", "year": 2024}])
        write_parquet_to_spec(df, "my-spec-bucket", "tb_unified_tmdb", "db_unified")

        mock_wr.s3.to_parquet.assert_called_once()
        call_kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert call_kwargs["path"] == "s3://my-spec-bucket/tb_unified_tmdb/"
        assert call_kwargs["database"] == "db_unified"
        assert call_kwargs["table"] == "tb_unified_tmdb"

    @patch("app.glue_agg.src.utils.wr")
    def test_partitions_by_media_type_and_year(self, mock_wr):
        df = pd.DataFrame([{"id": 1, "media_type": "movie", "year": 2024}])
        write_parquet_to_spec(df, "my-spec-bucket", "tb_unified_tmdb", "db_unified")

        call_kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert call_kwargs["partition_cols"] == ["media_type", "year"]

    @patch("app.glue_agg.src.utils.wr")
    def test_mode_is_overwrite_partitions(self, mock_wr):
        df = pd.DataFrame([{"id": 1, "media_type": "tv", "year": 2023}])
        write_parquet_to_spec(df, "my-spec-bucket", "tb_unified_tmdb", "db_unified")

        call_kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert call_kwargs["mode"] == "overwrite_partitions"

    @patch("app.glue_agg.src.utils.wr")
    def test_dataset_flag_is_true(self, mock_wr):
        df = pd.DataFrame([{"id": 1, "media_type": "movie", "year": 2024}])
        write_parquet_to_spec(df, "my-spec-bucket", "tb_unified_tmdb", "db_unified")

        call_kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert call_kwargs["dataset"] is True
