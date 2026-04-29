"""Unit tests for Glue ETL utility functions."""

import unittest
from unittest.mock import patch
import pandas as pd

from app.glue_etl.src.utils import process_tmdb


class TestProcessTmdb(unittest.TestCase):
    @patch("app.glue_etl.src.utils.wr")
    def test_partition_year_month(self, mock_wr):
        df = self._base_df()
        mock_wr.s3.read_json.return_value = df

        result = process_tmdb(
            source_path="s3://bucket-sor/",
            destination_path="s3://bucket-sot/",
            database="db_tmdb",
            table="movie_sot",
            partition_columns=["year", "month"],
            date_column="release_date"
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["partition_cols"], ["year", "month"])
        self.assertIn("year", kwargs["df"].columns)
        self.assertIn("month", kwargs["df"].columns)
        # Check returned partitions
        self.assertEqual(result["partitions"], ["year=2023/month=01", "year=2023/month=02", "year=2023/month=03"])

    def _base_df(self):
        return pd.DataFrame({
            "id": [1, 2, 3],
            "title": ["Movie 1", "Movie 2", "Movie 3"],
            "release_date": ["2023-01-01", "2023-02-01", "2023-03-01"]
        })

    @patch("app.glue_etl.src.utils.wr")
    def test_no_partition_does_not_add_columns(self, mock_wr):
        df = self._base_df()
        mock_wr.s3.read_json.return_value = df


        process_tmdb(
            source_path="s3://bucket-sor/",
            destination_path="s3://bucket-sot/",
            database="db_tmdb",
            table="movie_sot",
            partition_columns=None
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["partition_cols"], [])
        self.assertNotIn("year", kwargs["df"].columns)
        self.assertNotIn("month", kwargs["df"].columns)
        # Check returned partitions is empty
        self.assertEqual(result["partitions"], [])

    @patch("app.glue_etl.src.utils.wr")
    def test_custom_partition(self, mock_wr):
        df = self._base_df()
        df["custom"] = ["A", "B", "C"]  # Simulate custom column
        mock_wr.s3.read_json.return_value = df

        result = process_tmdb(
            source_path="s3://bucket-sor/",
            destination_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movie_sot",
            partition_columns=["custom"],
            date_column="custom"
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["partition_cols"], ["custom"])

if __name__ == "__main__":
    unittest.main()
