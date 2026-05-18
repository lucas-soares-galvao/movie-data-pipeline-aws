"""Raciocinio: valida regras DQ por tabela para evitar regressao de contrato de qualidade."""

import unittest
from app.glue_data_quality.src.rulesets_dq import rulesets_dq

class TestRulesetsDQ(unittest.TestCase):
    def test_countries_ruleset(self):
        rules = rulesets_dq["tb_configuration_countries_tmdb"]
        self.assertIn('IsComplete "iso_3166_1"', rules)
        self.assertIn('IsUnique "iso_3166_1"', rules)
        self.assertIn('RowCount > 0', rules)

    def test_languages_ruleset(self):
        rules = rulesets_dq["tb_configuration_languages_tmdb"]
        self.assertIn('IsComplete "iso_639_1"', rules)
        self.assertIn('IsUnique "iso_639_1"', rules)
        self.assertIn('RowCount > 0', rules)

    def test_genre_movie_ruleset(self):
        rules = rulesets_dq["tb_genre_movie_tmdb"]
        self.assertIn('IsComplete "id"', rules)
        self.assertIn('IsUnique "id"', rules)
        self.assertIn('IsComplete "name"', rules)


if __name__ == "__main__":
    unittest.main()
