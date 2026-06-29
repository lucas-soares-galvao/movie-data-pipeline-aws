# rulesets_dq é a "especificação de qualidade" do pipeline — regra mal-formatada
# ou tabela faltando faz o job Glue DQ falhar silenciosamente. Estes testes são
# um "contrato de cobertura": garantem que toda tabela conhecida tem regras
# e que estão no formato DQDL correto.

from src.rulesets_dq import rulesets_dq

EXPECTED_TABLES = [
    "configuration_countries",
    "configuration_languages",
    "genre_movie",
    "genre_tv",
    "discover_movie",
    "discover_tv",
    "details_movie",
    "details_tv",
    "watch_providers_movie",
    "watch_providers_tv",
    "watch_providers_ref_movie",
    "watch_providers_ref_tv",
    "now_playing_movie",
    "discover_unified",
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
        for table in [
            "discover_movie",
            "discover_tv",
            "discover_unified",
        ]:
            rules = rulesets_dq[table]
            assert any("vote_average" in r for r in rules), (
                f"Tabela '{table}' não valida vote_average"
            )

    def test_tables_with_id_have_completeness_and_uniqueness(self):
        """Tabelas que têm coluna 'id' devem checar IsComplete e IsUnique para ela."""
        tables_with_id = [
            "genre_movie",
            "genre_tv",
            "discover_movie",
            "discover_tv",
            "details_movie",
            "details_tv",
            "now_playing_movie",
        ]
        for table in tables_with_id:
            rules = rulesets_dq[table]
            assert any('IsComplete "id"' in r for r in rules), (
                f"Tabela '{table}' não tem IsComplete para 'id'"
            )
            assert any('IsUnique "id"' in r for r in rules), (
                f"Tabela '{table}' não tem IsUnique para 'id'"
            )

    def test_now_playing_validates_theater_dates(self):
        """now_playing_movie deve validar completude das datas de exibição."""
        rules = rulesets_dq["now_playing_movie"]
        assert any("theater_start_date" in r for r in rules), (
            "now_playing_movie não valida theater_start_date"
        )
        assert any("theater_end_date" in r for r in rules), (
            "now_playing_movie não valida theater_end_date"
        )

    def test_unified_validates_year_completeness(self):
        """discover_unified deve validar completude da coluna de partição year."""
        rules = rulesets_dq["discover_unified"]
        assert any('IsComplete "year"' in r for r in rules), (
            "discover_unified não tem IsComplete para 'year'"
        )

    def test_configuration_tables_validate_name_pt(self):
        """Tabelas de configuração devem validar completude da tradução name_pt."""
        for table in ["configuration_countries", "configuration_languages"]:
            rules = rulesets_dq[table]
            assert any('IsComplete "name_pt"' in r for r in rules), (
                f"Tabela '{table}' não valida completude de 'name_pt'"
            )

    def test_watch_providers_ref_validate_canonical_name(self):
        """Tabelas de referência de providers devem validar canonical_name."""
        for table in ["watch_providers_ref_movie", "watch_providers_ref_tv"]:
            rules = rulesets_dq[table]
            assert any('IsComplete "canonical_name"' in r for r in rules), (
                f"Tabela '{table}' não valida completude de 'canonical_name'"
            )

    def test_watch_providers_validate_provider_type_enum(self):
        """Tabelas de providers devem validar enum de provider_type."""
        for table in ["watch_providers_movie", "watch_providers_tv"]:
            rules = rulesets_dq[table]
            assert any("provider_type" in r and "in [" in r for r in rules), (
                f"Tabela '{table}' não valida enum de 'provider_type'"
            )

    def test_details_movie_validates_budget_and_revenue(self):
        """details_movie deve validar que budget e revenue são não-negativos."""
        rules = rulesets_dq["details_movie"]
        assert any("budget" in r for r in rules), (
            "details_movie não valida 'budget'"
        )
        assert any("revenue" in r for r in rules), (
            "details_movie não valida 'revenue'"
        )

    def test_discover_tables_validate_popularity(self):
        """Tabelas de discover devem validar que popularity é não-negativo."""
        for table in ["discover_movie", "discover_tv", "discover_unified"]:
            rules = rulesets_dq[table]
            assert any("popularity" in r for r in rules), (
                f"Tabela '{table}' não valida 'popularity'"
            )
