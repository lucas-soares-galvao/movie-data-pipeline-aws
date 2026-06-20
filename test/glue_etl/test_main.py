from unittest.mock import call, patch

import pandas as pd

import main as m

# Argumentos base reutilizados pelos testes (sem TABLE_TYPE nem YEAR —
# cada classe de teste define os valores que lhe são relevantes).
_BASE = {
    "S3_BUCKET_SOR": "my-sor",
    "S3_BUCKET_SOT": "my-sot",
    "MEDIA_TYPE": "movie",
    "DATABASE": "db_tmdb_movie_dev",
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "GLUE_AGG_JOB_NAME": "agg-job",
    "GLUE_DETAILS_JOB_NAME": "details-job",
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
            "TABLE_NAME": "tb_tmdb_discover_movie_dev",
            "YEAR": "2023",
            **overrides,
        }

    def test_calls_read_from_sor_with_discover_args(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "movie", "discover", "2023")

    def test_writes_to_discover_table_with_year_partition(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_tmdb_discover_movie_dev",
                database="db_tmdb_movie_dev",
                partition_cols=["year"],
                mode="overwrite_partitions",
            )

    def test_tv_media_type_forwarded_to_read_from_sor(self):
        df_mock = pd.DataFrame([{"id": 10, "year": "2022"}])
        args = self._args(
            MEDIA_TYPE="tv", YEAR="2022", TABLE_NAME="tb_tmdb_discover_tv_dev"
        )
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "tv", "discover", "2022")
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_tmdb_discover_tv_dev",
                database="db_tmdb_movie_dev",
                partition_cols=["year"],
                mode="overwrite_partitions",
            )

    def test_write_is_called_exactly_once(self):
        df_mock = pd.DataFrame([{"id": 1}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            assert mock_write.call_count == 1

    def test_triggers_data_quality_with_year(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            dq_call = call(
                "dq-job",
                TABLE_NAME="tb_tmdb_discover_movie_dev",
                DATABASE="db_tmdb_movie_dev",
                YEAR="2023",
            )
            assert dq_call in mock_trigger.call_args_list


# ---------------------------------------------------------------------------
# run() com TABLE_TYPE="genre"
# ---------------------------------------------------------------------------


class TestRunGenre:
    def _args(self, **overrides):
        return {
            **_BASE,
            "TABLE_TYPE": "genre",
            "TABLE_NAME": "tb_tmdb_genre_movie_dev",
            **overrides,
        }

    def test_calls_read_from_sor_with_genre_args(self):
        df_mock = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "movie", "genre", None)

    def test_writes_to_genre_table_without_partition(self):
        df_mock = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_tmdb_genre_movie_dev",
                database="db_tmdb_movie_dev",
                partition_cols=None,
                mode="overwrite",
            )

    def test_triggers_data_quality_without_year(self):
        df_mock = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            mock_trigger.assert_called_once_with(
                "dq-job",
                TABLE_NAME="tb_tmdb_genre_movie_dev",
                DATABASE="db_tmdb_movie_dev",
                YEAR=None,
            )


# ---------------------------------------------------------------------------
# run() com TABLE_TYPE="configuration"
# ---------------------------------------------------------------------------


class TestRunConfiguration:
    def _args(self, **overrides):
        return {
            **_BASE,
            "TABLE_TYPE": "configuration",
            "TABLE_NAME": "tb_tmdb_configuration_languages_dev",
            **overrides,
        }

    def test_calls_read_from_sor_with_configuration_args(self):
        df_mock = pd.DataFrame([{"iso_639_1": "pt"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "movie", "configuration", None)

    def test_writes_to_configuration_table_without_partition(self):
        df_mock = pd.DataFrame([{"iso_639_1": "pt"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_tmdb_configuration_languages_dev",
                database="db_tmdb_movie_dev",
                partition_cols=None,
                mode="overwrite",
            )

    def test_tv_uses_configuration_countries_table(self):
        df_mock = pd.DataFrame([{"iso_3166_1": "BR"}])
        args = self._args(
            MEDIA_TYPE="tv",
            TABLE_NAME="tb_tmdb_configuration_countries_dev",
        )
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "tv", "configuration", None)
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_tmdb_configuration_countries_dev",
                database="db_tmdb_movie_dev",
                partition_cols=None,
                mode="overwrite",
            )

    def test_triggers_data_quality_without_year(self):
        df_mock = pd.DataFrame([{"iso_639_1": "pt"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            mock_trigger.assert_called_once_with(
                "dq-job",
                TABLE_NAME="tb_tmdb_configuration_languages_dev",
                DATABASE="db_tmdb_movie_dev",
                YEAR=None,
            )


# ---------------------------------------------------------------------------
# Disparo condicional do Glue Details
# ---------------------------------------------------------------------------


class TestTriggerDetails:
    def _discover_args(self, **overrides):
        return {
            **_BASE,
            "TABLE_TYPE": "discover",
            "TABLE_NAME": "tb_tmdb_discover_movie_dev",
            "YEAR": "2023",
            **overrides,
        }

    def test_details_triggered_for_movie_discover(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        args = self._discover_args(MEDIA_TYPE="movie", TABLE_NAME="tb_tmdb_discover_movie_dev")
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            details_call = call(
                "details-job",
                MEDIA_TYPE="movie",
                YEAR="2023",
                END_YEAR="2026",
                DATABASE="db_tmdb_movie_dev",
            )
            assert details_call in mock_trigger.call_args_list

    def test_details_triggered_for_tv_discover(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        args = self._discover_args(MEDIA_TYPE="tv", TABLE_NAME="tb_tmdb_discover_tv_dev", DATABASE="db_tmdb_tv_dev")
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            details_call = call(
                "details-job",
                MEDIA_TYPE="tv",
                YEAR="2023",
                END_YEAR="2026",
                DATABASE="db_tmdb_tv_dev",
            )
            assert details_call in mock_trigger.call_args_list

    def test_details_not_triggered_for_genre_tv(self):
        # TABLE_TYPE=genre nunca aciona Details, independente do media_type.
        df_mock = pd.DataFrame([{"id": 28, "name": "Drama"}])
        args = {
            **_BASE,
            "TABLE_TYPE": "genre",
            "TABLE_NAME": "tb_tmdb_genre_tv_dev",
            "MEDIA_TYPE": "tv",
        }
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            details_calls = [
                c for c in mock_trigger.call_args_list
                if c.args[0] == "details-job"
            ]
            assert details_calls == []

    def test_details_triggered_exactly_once_per_discover_run(self):
        df_mock = pd.DataFrame([{"id": 1, "year": "2023"}])
        args = self._discover_args(MEDIA_TYPE="tv", TABLE_NAME="tb_tmdb_discover_tv_dev")
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            details_calls = [
                c for c in mock_trigger.call_args_list
                if c.args[0] == "details-job"
            ]
            assert len(details_calls) == 1


# ---------------------------------------------------------------------------
# run() com TABLE_TYPE="now_playing"
# ---------------------------------------------------------------------------


class TestRunNowPlaying:
    def _args(self, **overrides):
        return {
            **_BASE,
            "TABLE_TYPE": "now_playing",
            "TABLE_NAME": "tb_tmdb_now_playing_movie_dev",
            **overrides,
        }

    def test_calls_read_from_sor_with_now_playing_args(self):
        df_mock = pd.DataFrame([{"id": 1, "title": "Filme X"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock) as mock_read,
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_read.assert_called_once_with("my-sor", "movie", "now_playing", None)

    def test_writes_to_now_playing_table_without_partition(self):
        df_mock = pd.DataFrame([{"id": 1, "title": "Filme X"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=df_mock,
                s3_bucket_sot="my-sot",
                table_name="tb_tmdb_now_playing_movie_dev",
                database="db_tmdb_movie_dev",
                partition_cols=None,
                mode="overwrite",
            )

    def test_triggers_data_quality_without_year(self):
        df_mock = pd.DataFrame([{"id": 1, "title": "Filme X"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=self._args()),
            patch.object(m, "read_from_sor", return_value=df_mock),
            patch.object(m, "write_parquet_to_sot"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            mock_trigger.assert_called_once_with(
                "dq-job",
                TABLE_NAME="tb_tmdb_now_playing_movie_dev",
                DATABASE="db_tmdb_movie_dev",
                YEAR=None,
            )
