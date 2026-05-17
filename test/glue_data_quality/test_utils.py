"""Unit tests for Data Quality utility functions."""

from unittest.mock import patch
import unittest
from app.glue_data_quality.src.utils import (
    build_ruleset,
    parse_args,
    read_catalog_table,
    register_partition,
    rules_list_to_dqdl,
    run_data_quality,
    write_results,
)


class TestParseArgs(unittest.TestCase):
    def test_parse_args_with_optional_partitions(self):
        def fake_get_resolved_options(argv, keys):
            return {key: f"val_{key.lower()}" for key in keys}

        argv = [
            "script.py",
            "--DATABASE",
            "db",
            "--TABLE",
            "tb",
            "--S3_BUCKET_DATA_QUALITY",
            "bucket",
            "--PARTITIONS",
            "dt,region",
        ]

        with patch("app.glue_data_quality.src.utils.getResolvedOptions", fake_get_resolved_options):
            args = parse_args(argv)

        self.assertIn("PARTITIONS", args)
        self.assertEqual(args["DATABASE"], "val_database")

    def test_parse_args_without_optional_partitions(self):
        captured = {}

        def _fake_get_resolved_options(argv, keys):
            captured["keys"] = keys
            return {key: f"val_{key.lower()}" for key in keys}

        argv = [
            "script.py",
            "--DATABASE",
            "db",
            "--TABLE",
            "tb",
            "--S3_BUCKET_DATA_QUALITY",
            "bucket",
        ]

        with patch("app.glue_data_quality.src.utils.getResolvedOptions", _fake_get_resolved_options):
            parse_args(argv)

        self.assertNotIn("PARTITIONS", captured["keys"])


class TestHelperFunctions(unittest.TestCase):
    def test_build_ruleset_with_known_table(self):
        dqdl = build_ruleset("tb_configuration_countries_tmdb")
        self.assertIn('IsComplete "iso_3166_1"', dqdl)

    def test_build_ruleset_with_unknown_table(self):
        dqdl = build_ruleset("unknown_table")
        self.assertEqual(dqdl, 'Rules = [\n    RowCount > 0\n]')

    def test_read_catalog_table(self):
        class _FakeCatalog:
            def from_catalog(self, database, table_name):
                return {"database": database, "table": table_name}

        class _FakeDynamicFrame:
            def __init__(self):
                self.from_catalog = _FakeCatalog().from_catalog

        class _FakeGlueContext:
            def __init__(self):
                self.create_dynamic_frame = _FakeDynamicFrame()

        result = read_catalog_table(_FakeGlueContext(), "db", "tb")
        self.assertEqual(result, {"database": "db", "table": "tb"})

    def test_run_data_quality_calls_apply(self):
        class _FakeEvaluateDataQuality:
            @staticmethod
            def apply(**kwargs):
                return kwargs

        with patch("app.glue_data_quality.src.utils.EvaluateDataQuality", _FakeEvaluateDataQuality):
            result = run_data_quality(
                datasource="frame",
                ruleset="Rules = []",
            )

        self.assertEqual(result["frame"], "frame")
        self.assertEqual(result["ruleset"], "Rules = []")
        self.assertIn("publishing_options", result)

    def test_write_results_writes_to_expected_path(self):
        class _FakeLitValue:
            def __init__(self, value):
                self.value = value

        class _FakeWriter:
            def __init__(self):
                self.mode_value = None
                self.partition_by = None
                self.path_value = None

            def mode(self, value):
                self.mode_value = value
                return self

            def parquet(self, value):
                self.path_value = value

            def partitionBy(self, value):
                self.partition_by = value
                return self

        class _FakeDataFrame:
            def __init__(self):
                self.write = _FakeWriter()
                self.columns = []

            def withColumn(self, name, value):
                self.columns.append((name, value.value))
                return self

        fake_df = _FakeDataFrame()
        with patch(
            "app.glue_data_quality.src.utils.lit",
            lambda value: _FakeLitValue(value),
        ), patch(
            "app.glue_data_quality.src.utils.current_timestamp",
            lambda: _FakeLitValue("__now__"),
        ):
            write_results(fake_df, "bucket-dq", "tb_discover_movie_tmdb")

        self.assertIn(("source_table", "tb_discover_movie_tmdb"), fake_df.columns)
        self.assertIn(("partition", None), fake_df.columns)
        self.assertIn(("datetime_process", "__now__"), fake_df.columns)
        self.assertEqual(fake_df.write.mode_value, "append")
        self.assertEqual(fake_df.write.partition_by, "source_table")
        self.assertEqual(
            fake_df.write.path_value,
            "s3://bucket-dq/tmdb/tb_data_quality_tmdb/",
        )

    def test_write_results_returns_table_root_path(self):
        class _FakeLitValue:
            def __init__(self, value):
                self.value = value

        class _FakeWriter:
            def mode(self, _):
                return self

            def partitionBy(self, _):
                return self

            def parquet(self, _):
                return None

        class _FakeDataFrame:
            def __init__(self):
                self.write = _FakeWriter()

            def withColumn(self, _, __):
                return self

        with patch("app.glue_data_quality.src.utils.lit", lambda value: _FakeLitValue(value)), \
             patch("app.glue_data_quality.src.utils.current_timestamp", lambda: _FakeLitValue("__now__")):
            result = write_results(_FakeDataFrame(), "bucket-dq", "tb_discover_tv_tmdb")

        self.assertEqual(result, "s3://bucket-dq/tmdb/tb_data_quality_tmdb/")

    def test_register_partition_calls_awswrangler(self):
        class _FakeCatalog:
            def __init__(self):
                self.called_with = None

            def add_parquet_partitions(self, **kwargs):
                self.called_with = kwargs

        class _FakeWr:
            def __init__(self):
                self.catalog = _FakeCatalog()

        fake_wr = _FakeWr()
        table_root_path = "s3://bucket-dq/tmdb/tb_data_quality_tmdb/"

        with patch("app.glue_data_quality.src.utils.wr", fake_wr):
            register_partition("db_tmdb", "tb_discover_tv_tmdb", table_root_path)

        self.assertEqual(fake_wr.catalog.called_with["database"], "db_tmdb")
        self.assertEqual(fake_wr.catalog.called_with["table"], "tb_data_quality_tmdb")
        self.assertEqual(
            fake_wr.catalog.called_with["partitions_values"],
            {
                "s3://bucket-dq/tmdb/tb_data_quality_tmdb/source_table=tb_discover_tv_tmdb/": [
                    "tb_discover_tv_tmdb"
                ]
            },
        )


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
