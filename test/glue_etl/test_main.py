"""Testes de integração para app/glue_etl/main.py."""

from unittest.mock import patch

import pandas as pd

import main as m

# Argumentos base reutilizados pelos testes (sem TABLE_TYPE nem YEAR —
# cada classe de teste define os valores que lhe são relevantes).
_BASE = {
    "S3_BUCKET_SOR": "my-sor",
    "S3_BUCKET_SOT": "my-sot",
    "MEDIA_TYPE": "movie",
    "DATABASE": "db_tmdb",
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "GLUE_AGG_JOB_NAME": "agg-job",
    "GLUE_DETAILS_JOB_NAME": "details-job",
    "START_YEAR": "2025",
    "END_YEAR": "2026",
}


# ---------------------------------------------------------------------------
# run() com TABLE_TYPE="discover"
# ---------------------------------------------------------------------------


class TestRunDiscover:
    def _args(self, **overrides):
        return {
            **_BASE,
            "TABLE_TYPE": "discover",
            "TABLE_NAME": "tb_discover_movie_tmdb",
            "YEAR": "2023",
            **overrides,
        }

    def test_calls_read_from_sor_with_discover_args(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "movie", "discover", "2023")

    def test_writes_to_discover_table_with_year_partition(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_discover_movie_tmdb",
                database="db_tmdb",
                partition_cols=["year"],
                mode="overwrite_partitions",
            )

    def test_tv_media_type_forwarded_to_read_from_sor(self):
        df_mock = pd.DataFrame([{"id": 10, "year": "2022"}])
        args = self._args(
            MEDIA_TYPE="tv", YEAR="2022", TABLE_NAME="tb_discover_tv_tmdb"
        )
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "tv", "discover", "2022")
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_discover_tv_tmdb",
                database="db_tmdb",
                partition_cols=["year"],
                mode="overwrite_partitions",
            )

    def test_write_is_called_exactly_once(self):
        df_mock = pd.DataFrame([{"id": 1}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            assert mock_write.call_count == 1

    def test_triggers_data_quality_with_year(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality") as mock_dq,
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_dq.assert_called_once_with(
                dq_job_name="dq-job",
                table_name="tb_discover_movie_tmdb",
                database="db_tmdb",
                year="2023",
            )


# ---------------------------------------------------------------------------
# run() com TABLE_TYPE="genre"
# ---------------------------------------------------------------------------


class TestRunGenre:
    def _args(self, **overrides):
        return {
            **_BASE,
            "TABLE_TYPE": "genre",
            "TABLE_NAME": "tb_genre_movie_tmdb",
            **overrides,
        }

    def test_calls_read_from_sor_with_genre_args(self):
        df_mock = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "movie", "genre", None)

    def test_writes_to_genre_table_without_partition(self):
        df_mock = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_genre_movie_tmdb",
                database="db_tmdb",
                partition_cols=None,
                mode="overwrite",
            )

    def test_triggers_data_quality_without_year(self):
        df_mock = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality") as mock_dq,
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_dq.assert_called_once_with(
                dq_job_name="dq-job",
                table_name="tb_genre_movie_tmdb",
                database="db_tmdb",
                year=None,
            )


# ---------------------------------------------------------------------------
# run() com TABLE_TYPE="configuration"
# ---------------------------------------------------------------------------


class TestRunConfiguration:
    def _args(self, **overrides):
        return {
            **_BASE,
            "TABLE_TYPE": "configuration",
            "TABLE_NAME": "tb_configuration_languages_tmdb",
            **overrides,
        }

    def test_calls_read_from_sor_with_configuration_args(self):
        df_mock = pd.DataFrame([{"iso_639_1": "pt"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "movie", "configuration", None)

    def test_writes_to_configuration_table_without_partition(self):
        df_mock = pd.DataFrame([{"iso_639_1": "pt"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_configuration_languages_tmdb",
                database="db_tmdb",
                partition_cols=None,
                mode="overwrite",
            )

    def test_tv_uses_configuration_countries_table(self):
        df_mock = pd.DataFrame([{"iso_3166_1": "BR"}])
        args = self._args(
            MEDIA_TYPE="tv",
            TABLE_NAME="tb_configuration_countries_tmdb",
        )
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "tv", "configuration", None)
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_configuration_countries_tmdb",
                database="db_tmdb",
                partition_cols=None,
                mode="overwrite",
            )

    def test_triggers_data_quality_without_year(self):
        df_mock = pd.DataFrame([{"iso_639_1": "pt"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality") as mock_dq,
            patch.object(m, "trigger_details"),
        ):
            m.main()
            mock_dq.assert_called_once_with(
                dq_job_name="dq-job",
                table_name="tb_configuration_languages_tmdb",
                database="db_tmdb",
                year=None,
            )


# ---------------------------------------------------------------------------
# Disparo condicional do Glue Details
# ---------------------------------------------------------------------------


class TestTriggerDetails:
    def _discover_args(self, **overrides):
        return {
            **_BASE,
            "TABLE_TYPE": "discover",
            "TABLE_NAME": "tb_discover_movie_tmdb",
            "YEAR": "2023",
            **overrides,
        }

    def test_details_triggered_for_movie_discover(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        args = self._discover_args(MEDIA_TYPE="movie", TABLE_NAME="tb_discover_movie_tmdb")
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details") as mock_details,
        ):
            m.main()
            mock_details.assert_called_once_with(
                details_job_name="details-job",
                media_type="movie",
                year="2023",
                end_year="2026",
                database="db_tmdb",
            )

    def test_details_triggered_for_tv_discover(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        args = self._discover_args(MEDIA_TYPE="tv", TABLE_NAME="tb_discover_tv_tmdb", DATABASE="db_tv_tmdb")
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details") as mock_details,
        ):
            m.main()
            mock_details.assert_called_once_with(
                details_job_name="details-job",
                media_type="tv",
                year="2023",
                end_year="2026",
                database="db_tv_tmdb",
            )

    def test_details_not_triggered_for_genre_tv(self):
        # TABLE_TYPE=genre nunca aciona Details, independente do media_type.
        df_mock = pd.DataFrame([{"id": 28, "name": "Drama"}])
        args = {
            **_BASE,
            "TABLE_TYPE": "genre",
            "TABLE_NAME": "tb_genre_tv_tmdb",
            "MEDIA_TYPE": "tv",
        }
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details") as mock_details,
        ):
            m.main()
            mock_details.assert_not_called()

    def test_details_triggered_exactly_once_per_discover_run(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        args = self._discover_args(MEDIA_TYPE="tv", TABLE_NAME="tb_discover_tv_tmdb")
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_details") as mock_details,
        ):
            m.main()
            assert mock_details.call_count == 1
