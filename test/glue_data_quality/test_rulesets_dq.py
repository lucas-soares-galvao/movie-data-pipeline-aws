"""Testes unitários para app/glue_data_quality/src/rulesets_dq.py."""

from src.rulesets_dq import rulesets_dq

# Tabelas que devem obrigatoriamente ter regras definidas
EXPECTED_TABLES = [
    "tb_configuration_countries_tmdb",
    "tb_configuration_languages_tmdb",
    "tb_genre_movie_tmdb",
    "tb_genre_tv_tmdb",
    "tb_discover_movie_tmdb",
    "tb_discover_tv_tmdb",
    "tb_details_movie_tmdb",
    "tb_details_tv_tmdb",
    "tb_watch_providers_movie_tmdb",
    "tb_watch_providers_tv_tmdb",
]


class TestRulesetsDq:
    def test_all_expected_tables_are_present(self):
        """Todas as tabelas conhecidas devem ter um bloco de regras."""
        for table in EXPECTED_TABLES:
            assert table in rulesets_dq, (
                f"Tabela '{table}' não encontrada em rulesets_dq"
            )

    def test_each_table_has_at_least_one_rule(self):
        """Cada tabela deve ter pelo menos uma regra definida."""
        for table, rules in rulesets_dq.items():
            assert len(rules) > 0, f"Tabela '{table}' não tem regras definidas"

    def test_all_rules_are_strings(self):
        """Toda regra deve ser uma string (formato DQDL)."""
        for table, rules in rulesets_dq.items():
            for rule in rules:
                assert isinstance(rule, str), (
                    f"Regra '{rule}' da tabela '{table}' não é string"
                )

    def test_no_empty_rules(self):
        """Nenhuma regra pode ser string vazia ou somente espaços."""
        for table, rules in rulesets_dq.items():
            for rule in rules:
                assert rule.strip() != "", f"Tabela '{table}' tem regra vazia"

    def test_all_tables_have_row_count_rule(self):
        """Toda tabela deve verificar que existem linhas (RowCount > 0)."""
        for table, rules in rulesets_dq.items():
            assert any("RowCount" in r for r in rules), (
                f"Tabela '{table}' não tem regra RowCount"
            )

    def test_discover_tables_validate_vote_average(self):
        """Tabelas de discover devem validar o intervalo de vote_average."""
        for table in ["tb_discover_movie_tmdb", "tb_discover_tv_tmdb"]:
            rules = rulesets_dq[table]
            assert any("vote_average" in r for r in rules), (
                f"Tabela '{table}' não valida vote_average"
            )

    def test_tables_with_id_have_completeness_and_uniqueness(self):
        """Tabelas que têm coluna 'id' devem checar IsComplete e IsUnique para ela."""
        tables_with_id = [
            "tb_genre_movie_tmdb",
            "tb_genre_tv_tmdb",
            "tb_discover_movie_tmdb",
            "tb_discover_tv_tmdb",
            "tb_details_movie_tmdb",
            "tb_details_tv_tmdb",
        ]
        for table in tables_with_id:
            rules = rulesets_dq[table]
            assert any('IsComplete "id"' in r for r in rules), (
                f"Tabela '{table}' não tem IsComplete para 'id'"
            )
            assert any('IsUnique "id"' in r for r in rules), (
                f"Tabela '{table}' não tem IsUnique para 'id'"
            )
