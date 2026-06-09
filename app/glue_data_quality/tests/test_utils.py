"""Testes unitários para app/glue_data_quality/src/utils.py."""

from unittest.mock import MagicMock, patch

import pytest

from app.glue_data_quality.src.utils import get_ruleset, notify_failed_outcomes


# ---------------------------------------------------------------------------
# get_ruleset
# ---------------------------------------------------------------------------

class TestGetRuleset:
    def test_returns_dqdl_string_for_known_table(self):
        ruleset = get_ruleset("tb_genre_movie_tmdb")
        assert ruleset.startswith("Rules = [")
        assert ruleset.endswith("]")

    def test_contains_all_rules_for_table(self):
        ruleset = get_ruleset("tb_genre_movie_tmdb")
        assert 'IsComplete "id"' in ruleset
        assert 'IsUnique "id"' in ruleset
        assert 'IsComplete "name"' in ruleset
        assert "RowCount > 0" in ruleset

    def test_raises_key_error_for_unknown_table(self):
        with pytest.raises(KeyError, match="tabela_inexistente"):
            get_ruleset("tabela_inexistente")

    def test_rules_separated_by_comma(self):
        ruleset = get_ruleset("tb_genre_movie_tmdb")
        # Cada regra deve estar em linha separada por vírgula
        lines = [line.strip() for line in ruleset.splitlines() if line.strip() not in ("Rules = [", "]")]
        for line in lines[:-1]:
            assert line.endswith(","), f"Linha sem vírgula: {line!r}"

    def test_configuration_countries_rules(self):
        ruleset = get_ruleset("tb_configuration_countries_tmdb")
        assert 'IsComplete "iso_3166_1"' in ruleset
        assert 'IsUnique "iso_3166_1"' in ruleset
        assert 'IsComplete "native_name"' in ruleset

    def test_configuration_languages_rules(self):
        ruleset = get_ruleset("tb_configuration_languages_tmdb")
        assert 'IsComplete "iso_639_1"' in ruleset
        assert 'IsUnique "iso_639_1"' in ruleset


# ---------------------------------------------------------------------------
# notify_failed_outcomes
# ---------------------------------------------------------------------------

def _make_spark_df(rows: list[dict]):
    """Cria um mock de Spark DataFrame a partir de uma lista de dicionários."""
    mock_df = MagicMock()

    # Simula filter retornando novo mock com count e collect configurados
    failed = [r for r in rows if r.get("outcome") == "Failed"]

    failed_df = MagicMock()
    failed_df.count.return_value = len(failed)
    failed_df.select.return_value.collect.return_value = [
        MagicMock(**{"__getitem__": lambda self, k: r[k]}) for r in failed
    ]

    # Configura rows collect com comportamento de Row do Spark
    spark_rows = []
    for r in failed:
        row = MagicMock()
        row.__getitem__ = lambda self, k, _r=r: _r[k]
        spark_rows.append(row)

    failed_df.select.return_value.collect.return_value = spark_rows
    mock_df.filter.return_value = failed_df
    return mock_df


class TestNotifyFailedOutcomes:
    @patch("app.glue_data_quality.src.utils.boto3")
    def test_does_not_publish_when_all_passed(self, mock_boto3):
        mock_sns = MagicMock()
        mock_boto3.client.return_value = mock_sns

        df = _make_spark_df([
            {"outcome": "Passed", "rule": 'IsComplete "id"', "failure_reason": None},
        ])
        notify_failed_outcomes(df, "tb_genre_movie_tmdb", "arn:aws:sns:us-east-1:123:topic", "dev")

        mock_sns.publish.assert_not_called()

    @patch("app.glue_data_quality.src.utils.boto3")
    def test_publishes_when_rule_fails(self, mock_boto3):
        mock_sns = MagicMock()
        mock_boto3.client.return_value = mock_sns

        df = _make_spark_df([
            {"outcome": "Failed", "rule": 'IsComplete "id"', "failure_reason": "10 nulls found"},
        ])
        notify_failed_outcomes(df, "tb_genre_movie_tmdb", "arn:aws:sns:us-east-1:123:topic", "prod")

        mock_sns.publish.assert_called_once()
        call_kwargs = mock_sns.publish.call_args.kwargs
        assert call_kwargs["TopicArn"] == "arn:aws:sns:us-east-1:123:topic"
        assert "[PROD]" in call_kwargs["Subject"]
        assert "tb_genre_movie_tmdb" in call_kwargs["Message"]

    @patch("app.glue_data_quality.src.utils.boto3")
    def test_includes_year_in_message_when_provided(self, mock_boto3):
        mock_sns = MagicMock()
        mock_boto3.client.return_value = mock_sns

        df = _make_spark_df([
            {"outcome": "Failed", "rule": "RowCount > 0", "failure_reason": "0 rows"},
        ])
        notify_failed_outcomes(
            df, "tb_discover_movie_tmdb", "arn:aws:sns:us-east-1:123:topic", "dev", year="2024"
        )

        message = mock_sns.publish.call_args.kwargs["Message"]
        assert "year=2024" in message

    @patch("app.glue_data_quality.src.utils.boto3")
    def test_does_not_include_year_line_when_none(self, mock_boto3):
        mock_sns = MagicMock()
        mock_boto3.client.return_value = mock_sns

        df = _make_spark_df([
            {"outcome": "Failed", "rule": "RowCount > 0", "failure_reason": "0 rows"},
        ])
        notify_failed_outcomes(
            df, "tb_genre_movie_tmdb", "arn:aws:sns:us-east-1:123:topic", "dev"
        )

        message = mock_sns.publish.call_args.kwargs["Message"]
        assert "Partição" not in message
