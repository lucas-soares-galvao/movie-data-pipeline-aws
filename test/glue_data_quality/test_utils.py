"""Unit tests for Data Quality utility functions."""

import unittest
from app.glue_data_quality.src.utils import rules_list_to_dqdl

class TestRulesListToDQDL(unittest.TestCase):
    def test_generates_dqdl_for_nonempty_list(self):
        rules = [
            'IsComplete "id"',
            'IsUnique "id"',
            'RowCount > 0'
        ]
        expected = (
            'Rules = [\n'
            '    IsComplete "id",\n'
            '    IsUnique "id",\n'
            '    RowCount > 0\n'
            ']'
        )
        self.assertEqual(rules_list_to_dqdl(rules), expected)

    def test_generates_minimal_dqdl_for_empty_list(self):
        expected = 'Rules = [\n    RowCount > 0\n]'
        self.assertEqual(rules_list_to_dqdl([]), expected)


if __name__ == "__main__":
    unittest.main()
