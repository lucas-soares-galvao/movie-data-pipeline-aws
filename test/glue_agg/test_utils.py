"""Testes unitarios para app/glue_agg/src/utils.py."""

from unittest.mock import patch

import pandas as pd

from src.utils import run_athena_query


class TestRunAthenaQuery:
    def test_passes_sql_with_image_columns_to_wrangler(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(database="db_tmdb", s3_bucket_temp="my-temp")

            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "AS poster_url" in sql
            assert "AS backdrop_url" in sql
            assert "https://image.tmdb.org/t/p/w780" in sql
            assert "https://image.tmdb.org/t/p/w1280" in sql
            assert "tb_discover_movie_tmdb" in sql
            assert "tb_discover_tv_tmdb" in sql
            assert "runtime" in sql
            assert "number_of_seasons" in sql
            assert "number_of_episodes" in sql
            assert "episode_run_time" in sql

    def test_uses_expected_wrangler_execution_args(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(database="db_tmdb", s3_bucket_temp="my-temp")

            mock_read.assert_called_once()
            _, kwargs = mock_read.call_args
            assert kwargs["database"] == "db_tmdb"
            assert kwargs["s3_output"] == "s3://my-temp/athena/glue_agg/"
            assert kwargs["ctas_approach"] is True
