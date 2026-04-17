"""Unit tests for Data Quality helper functions."""

import unittest

from app.glue_data_quality.src.utils import has_required_columns


class TestHasRequiredColumns(unittest.TestCase):
    """Guarantee required-column checks work as expected."""

    def test_returns_true_when_all_required_columns_exist(self):
        columns = {"id", "title", "release_year", "genre"}
        required = {"id", "title", "release_year"}
        self.assertTrue(has_required_columns(columns, required))

    def test_returns_false_when_a_required_column_is_missing(self):
        columns = {"id", "title"}
        required = {"id", "title", "release_year"}
        self.assertFalse(has_required_columns(columns, required))


if __name__ == "__main__":
    unittest.main()
