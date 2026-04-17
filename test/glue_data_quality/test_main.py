"""Tests for Glue Data Quality main module."""

import unittest

from app.glue_data_quality.main import validate_dataset


class TestDataQualityMain(unittest.TestCase):
    """Validate user-facing messages returned by validate_dataset."""

    def test_validate_dataset_approved(self):
        columns = {"id", "title", "release_year", "genre"}
        expected = "Dataset approved in data quality validation."
        self.assertEqual(validate_dataset(columns), expected)

    def test_validate_dataset_rejected(self):
        columns = {"id", "title"}
        expected = "Dataset rejected in data quality validation."
        self.assertEqual(validate_dataset(columns), expected)


if __name__ == "__main__":
    unittest.main()
