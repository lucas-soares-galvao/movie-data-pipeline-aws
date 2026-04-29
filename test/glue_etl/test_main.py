
"""Tests for the main module of Glue ETL."""

import os
import sys
import unittest
from unittest.mock import MagicMock

 # Glue ETL main.py uses 'from src.utils import ...' without a qualified package,
# so app/glue_etl needs to be in sys.path during import.
_GLUE_ETL_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "app", "glue_etl"
)
_GLUE_ETL_DIR = os.path.abspath(_GLUE_ETL_DIR)


def _setup_mocks(resolved_args):
    """Adds mocks for awsglue and src.utils to sys.modules."""
    mock_utils_mod = MagicMock()
    mock_utils_mod.getResolvedOptions.return_value = resolved_args
    sys.modules.setdefault("awsglue", MagicMock())
    sys.modules["awsglue.utils"] = mock_utils_mod

    mock_src_utils = MagicMock()
    sys.modules["src"] = MagicMock(utils=mock_src_utils)
    sys.modules["src.utils"] = mock_src_utils
    return mock_src_utils


def _reload_main():
    sys.modules.pop("app.glue_etl.main", None)
    if _GLUE_ETL_DIR not in sys.path:
        sys.path.insert(0, _GLUE_ETL_DIR)
    import app.glue_etl.main  # noqa: F401



class TestGlueEtlMain(unittest.TestCase):
    def test_calls_glue_data_quality_with_partitions(self):
        mock_src_utils = _setup_mocks(self._DEFAULT_ARGS)
        # Simulate process_tmdb returning partitions for discover and empty for genre
        mock_src_utils.process_tmdb.side_effect = [
            {"processed_rows": 10, "partitions": ["year=2023/month=01", "year=2023/month=02"]},
            {"processed_rows": 5, "partitions": []},
            {"processed_rows": 0, "partitions": []}
        ]
        mock_src_utils.call_glue_data_quality.return_value = {"job_name": "glue-data-quality-dev", "job_run_id": "123"}

        _reload_main()

        expected_calls = [
            (('glue-data-quality-dev',), {'partition_columns': 'year,month', 'partition_values': ["year=2023/month=01", "year=2023/month=02"]}),
            (('glue-data-quality-dev',), {'partition_columns': '', 'partition_values': None}),
            (('glue-data-quality-dev',), {'partition_columns': '', 'partition_values': None})
        ]
        actual_calls = [(c.args, c.kwargs) for c in mock_src_utils.call_glue_data_quality.call_args_list]
        self.assertEqual(actual_calls, expected_calls)

    _DEFAULT_ARGS = {
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
        "PARTITION_COLUMNS": "year,month"
    }

    def tearDown(self):
        sys.modules.pop("app.glue_etl.main", None)
        for key in [k for k in sys.modules if k.startswith("awsglue")]:
            del sys.modules[key]
        for key in ["src", "src.utils"]:
            sys.modules.pop(key, None)
        if _GLUE_ETL_DIR in sys.path:
            sys.path.remove(_GLUE_ETL_DIR)

    def test_calls_process_tmdb_with_correct_arguments(self):
        mock_src_utils = _setup_mocks(self._DEFAULT_ARGS)
        mock_src_utils.process_tmdb.return_value = {"processed_rows": 10}

        _reload_main()

        expected_calls = [
            dict(source_path='s3://bucket-sor/tmdb/discover/movie/', destination_path='s3://bucket-sot/tb_discover_movie_tmdb/', database='db_tmdb', table='tb_discover_movie_tmdb', partition_columns=['year', 'month'], date_column='release_date'),
            dict(source_path='s3://bucket-sor/tmdb/genre/movie/', destination_path='s3://bucket-sot/tb_genre_movie_tmdb/', database='db_tmdb', table='tb_genre_movie_tmdb', partition_columns=[], date_column=None),
            dict(source_path='s3://bucket-sor/tmdb/configuration/languages/', destination_path='s3://bucket-sot/tb_configuration_movie_tmdb/', database='db_tmdb', table='tb_configuration_movie_tmdb', partition_columns=[], date_column=None),
        ]
        actual_calls = [call.kwargs for call in mock_src_utils.process_tmdb.call_args_list]
        self.assertEqual(actual_calls, expected_calls)

    def test_main_runs_without_exception(self):
        mock_src_utils = _setup_mocks(self._DEFAULT_ARGS)
        mock_src_utils.process_tmdb.return_value = {"processed_rows": 5}

        try:
            _reload_main()
        except Exception as exc:
            self.fail(f"main.py raised an unexpected exception: {exc}")


if __name__ == "__main__":
    unittest.main()
