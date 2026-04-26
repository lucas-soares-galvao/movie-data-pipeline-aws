"""Unit tests for Data Quality helper functions."""

import unittest

from app.glue_data_quality.src.utils import has_required_columns


class TestHasRequiredColumns(unittest.TestCase):
    """Ensures that the required columns check works as expected."""

    def test_returns_true_when_all_columns_exist(self):
        columns = {"id", "title", "release_year", "genre"}
        required_columns = {"id", "title", "release_year"}
        self.assertTrue(has_required_columns(columns, required_columns))

    def test_returns_false_when_column_is_missing(self):
        columns = {"id", "title"}
        required_columns = {"id", "title", "release_year"}
        self.assertFalse(has_required_columns(columns, required_columns))


if __name__ == "__main__":
    unittest.main()
