
"""Tests for the main module of Glue ETL."""

import unittest
from unittest.mock import patch

from app.glue_etl import main


DEFAULT_ARGS = {
    "GLUE_CATALOG_DATABASE": "db_tmdb",
    "GLUE_CATALOG_TABLE": "movie_sot",
    "S3_BUCKET_SOR": "bucket-sor",
    "S3_BUCKET_SOT": "bucket-sot",
    "GLUE_DATA_QUALITY_JOB_NAME": "glue-data-quality-dev",
    "MEDIA_TYPE": "movie",
    "DATABASE": "db_tmdb",
    "DISCOVER_TABLE": "tb_discover_movie_tmdb",
    "GENRE_TABLE": "tb_genre_movie_tmdb",
    "CONFIGURATION_TABLE": "tb_configuration_movie_tmdb",
    "CONFIGURATION": "languages",
    "PARTITION_COLUMNS": "year,month",
    "YEAR": "2023"
}

STATIC_ARGS = {
    **DEFAULT_ARGS,
    "TABLE_SCOPE": "static"
}

DISCOVER_ARGS = {
    **DEFAULT_ARGS,
    "TABLE_SCOPE": "discover"
}


class TestGlueEtlMain(unittest.TestCase):
    def test_calls_glue_data_quality_with_partitions(self):
        with patch("app.glue_etl.src.utils.process_tmdb") as mock_process_tmdb, \
            patch("app.glue_etl.src.utils.call_glue_data_quality") as mock_call_glue_data_quality:
            mock_process_tmdb.side_effect = [
                {"partitions": ["year=2023/month=01", "year=2023/month=02"]},
                {"partitions": []},
                {"partitions": []}
            ]
            mock_call_glue_data_quality.return_value = {"job_name": "glue-data-quality-dev", "job_run_id": "123"}

            main.run_etl(DEFAULT_ARGS)

            expected_calls = [
                (
                    "glue-data-quality-dev",
                    {
                        "database": "db_tmdb",
                        "table": "tb_discover_movie_tmdb",
                        "partition_values": ["year=2023"]
                    }
                ),
                (
                    "glue-data-quality-dev",
                    {
                        "database": "db_tmdb",
                        "table": "tb_genre_movie_tmdb",
                        "partition_values": None
                    }
                ),
                (
                    "glue-data-quality-dev",
                    {
                        "database": "db_tmdb",
                        "table": "tb_configuration_movie_tmdb",
                        "partition_values": None
                    }
                )
            ]
            actual_calls = [(c.args[0], c.kwargs) for c in mock_call_glue_data_quality.call_args_list]
            self.assertEqual(len(actual_calls), len(expected_calls))
            for (actual_job, actual_kwargs), (expected_job, expected_kwargs) in zip(actual_calls, expected_calls):
                self.assertEqual(actual_job, expected_job)
                self.assertDictEqual(actual_kwargs, expected_kwargs)

    def test_calls_process_tmdb_with_correct_arguments(self):
        with patch("app.glue_etl.src.utils.process_tmdb") as mock_process_tmdb, \
            patch("app.glue_etl.src.utils.call_glue_data_quality"):
            mock_process_tmdb.return_value = {"partitions": []}

            main.run_etl(DEFAULT_ARGS)

            expected_calls = [
                dict(source_path="s3://bucket-sor/tmdb/discover/movie/", destination_path="s3://bucket-sot/tmdb/tb_discover_movie_tmdb/", database="db_tmdb", table="tb_discover_movie_tmdb", partition_columns=["year", "month"], date_column="release_date"),
                dict(source_path="s3://bucket-sor/tmdb/genre/movie/", destination_path="s3://bucket-sot/tmdb/tb_genre_movie_tmdb/", database="db_tmdb", table="tb_genre_movie_tmdb", partition_columns=[], date_column=None),
                dict(source_path="s3://bucket-sor/tmdb/configuration/languages/", destination_path="s3://bucket-sot/tmdb/tb_configuration_movie_tmdb/", database="db_tmdb", table="tb_configuration_movie_tmdb", partition_columns=[], date_column=None),
            ]
            actual_calls = [call.kwargs for call in mock_process_tmdb.call_args_list]
            self.assertEqual(actual_calls, expected_calls)

    def test_discovers_scope_processes_only_requested_year(self):
        with patch("app.glue_etl.src.utils.process_tmdb") as mock_process_tmdb, \
            patch("app.glue_etl.src.utils.call_glue_data_quality") as mock_call_glue_data_quality:
            mock_process_tmdb.return_value = {"partitions": ["year=2023/month=01"]}

            main.run_etl(DISCOVER_ARGS)

            mock_process_tmdb.assert_called_once_with(
                source_path="s3://bucket-sor/tmdb/discover/movie/year=2023/",
                destination_path="s3://bucket-sot/tmdb/tb_discover_movie_tmdb/",
                database="db_tmdb",
                table="tb_discover_movie_tmdb",
                partition_columns=["year", "month"],
                date_column="release_date"
            )
            mock_call_glue_data_quality.assert_called_once_with(
                "glue-data-quality-dev",
                database="db_tmdb",
                table="tb_discover_movie_tmdb",
                partition_values=["year=2023"]
            )

    def test_static_scope_skips_discover(self):
        with patch("app.glue_etl.src.utils.process_tmdb") as mock_process_tmdb, \
            patch("app.glue_etl.src.utils.call_glue_data_quality") as mock_call_glue_data_quality:
            mock_process_tmdb.return_value = {"partitions": []}

            main.run_etl(STATIC_ARGS)

            expected_calls = [
                dict(source_path="s3://bucket-sor/tmdb/genre/movie/", destination_path="s3://bucket-sot/tmdb/tb_genre_movie_tmdb/", database="db_tmdb", table="tb_genre_movie_tmdb", partition_columns=[], date_column=None),
                dict(source_path="s3://bucket-sor/tmdb/configuration/languages/", destination_path="s3://bucket-sot/tmdb/tb_configuration_movie_tmdb/", database="db_tmdb", table="tb_configuration_movie_tmdb", partition_columns=[], date_column=None),
            ]
            actual_calls = [call.kwargs for call in mock_process_tmdb.call_args_list]
            self.assertEqual(actual_calls, expected_calls)
            self.assertEqual(mock_call_glue_data_quality.call_count, 2)

    def test_main_runs_without_exception(self):
        with patch("app.glue_etl.src.utils.process_tmdb") as mock_process_tmdb, \
            patch("app.glue_etl.src.utils.call_glue_data_quality"):
            mock_process_tmdb.return_value = {"partitions": []}

            try:
                main.run_etl(DEFAULT_ARGS)
            except Exception as exc:
                self.fail(f"main.py raised an unexpected exception: {exc}")


if __name__ == "__main__":
    unittest.main()
