"""
test_rulesets_dq.py — Testes unitários para app/glue_data_quality/src/rulesets_dq.py.

==============================================================================
O QUE ESTE ARQUIVO TESTA?
==============================================================================
Testa a estrutura do dicionário `rulesets_dq` que define as regras de
qualidade de dados para cada tabela do pipeline.

POR QUE TESTAR UM DICIONÁRIO?
  rulesets_dq é a "especificação de qualidade" do pipeline — qualquer erro
  aqui (regra mal-formatada, tabela faltando, lista vazia) faz o job Glue DQ
  falhar silenciosamente ou pular validações. Estes testes funcionam como
  um "contrato de cobertura": garantem que toda tabela conhecida tem regras
  e que as regras têm o formato correto do DQDL.

SOBRE O FORMATO DQDL (Data Quality Definition Language):
  As regras são strings como:
    'IsComplete "id"'                → coluna "id" não pode ter nulos
    'IsUnique "id"'                  → coluna "id" não pode ter duplicatas
    'RowCount > 0'                   → tabela deve ter ao menos 1 linha
    'ColumnValues "vote_average" between 0 and 10'  → intervalo válido
  get_ruleset() concatena essas strings num bloco "Rules = [...]".

TABELAS ESPERADAS (EXPECTED_TABLES):
  São todas as tabelas do pipeline que passam pelo job de Data Quality.
  Se uma tabela nova for adicionada ao pipeline mas não tiver regras em
  rulesets_dq, os testes vão falhar com uma mensagem clara indicando qual
  tabela está faltando.

TESTES:
  test_all_expected_tables_are_present     → cobertura: toda tabela tem entrada
  test_each_table_has_at_least_one_rule    → nenhuma tabela tem lista vazia
  test_all_rules_are_strings               → formato correto (DQDL é string)
  test_no_empty_rules                      → sem strings vazias ou com só espaços
  test_all_tables_have_row_count_rule      → toda tabela verifica se tem linhas
  test_discover_tables_validate_vote_average → tabelas de discover validam nota
  test_tables_with_id_have_completeness_and_uniqueness → id deve ser completo e único
"""

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
