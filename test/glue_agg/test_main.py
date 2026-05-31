"""Testes de integração para app/glue_agg/main.py."""

from unittest.mock import patch

import pandas as pd

import main as m

_BASE_ARGS = {
    "S3_BUCKET_SPEC": "my-spec",
    "S3_BUCKET_TEMP": "my-temp",
    "DATABASE": "db_tmdb",
    "TABLE_NAME": "tb_discover_unified_tmdb",
}

_DF_MOCK = pd.DataFrame([
    {"id": 1, "media_type": "movie", "title": "Film A", "year": "2023"},
    {"id": 2, "media_type": "tv",    "title": "Show B", "year": "2022"},
])


class TestMain:
    def test_calls_run_athena_query_with_correct_args(self):
        with patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS), \
             patch.object(m, "run_athena_query", return_value=_DF_MOCK) as mock_query, \
             patch.object(m, "write_parquet_to_spec"):
            m.main()
            mock_query.assert_called_once_with(
                database="db_tmdb",
                s3_bucket_temp="my-temp",
            )

    def test_calls_write_parquet_to_spec_with_correct_args(self):
        with patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS), \
             patch.object(m, "run_athena_query", return_value=_DF_MOCK), \
             patch.object(m, "write_parquet_to_spec") as mock_write:
            m.main()
            mock_write.assert_called_once_with(
                df=_DF_MOCK,
                s3_bucket_spec="my-spec",
                table_name="tb_discover_unified_tmdb",
                database="db_tmdb",
            )

    def test_write_receives_dataframe_returned_by_query(self):
        df_custom = pd.DataFrame([{"id": 99, "media_type": "movie", "year": "2024"}])
        with patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS), \
             patch.object(m, "run_athena_query", return_value=df_custom), \
             patch.object(m, "write_parquet_to_spec") as mock_write:
            m.main()
            actual_df = mock_write.call_args.kwargs["df"]
            pd.testing.assert_frame_equal(actual_df, df_custom)

    def test_pipeline_runs_without_exceptions(self):
        with patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS), \
             patch.object(m, "run_athena_query", return_value=_DF_MOCK), \
             patch.object(m, "write_parquet_to_spec"):
            m.main()  # deve concluir sem levantar excecao

    def test_write_called_exactly_once(self):
        with patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS), \
             patch.object(m, "run_athena_query", return_value=_DF_MOCK), \
             patch.object(m, "write_parquet_to_spec") as mock_write:
            m.main()
            assert mock_write.call_count == 1

    def test_query_called_exactly_once(self):
        with patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS), \
             patch.object(m, "run_athena_query", return_value=_DF_MOCK) as mock_query, \
             patch.object(m, "write_parquet_to_spec"):
            m.main()
            assert mock_query.call_count == 1
