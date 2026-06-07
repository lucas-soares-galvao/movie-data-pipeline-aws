"""Testes unitários para app/glue_etl/src/utils.py."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd

from src.utils import (
    _fetch_tmdb_detail,
    enrich_with_runtime,
    read_from_sor,
    trigger_data_quality,
    write_parquet_to_sot,
)


# ---------------------------------------------------------------------------
# Helpers compartilhados
# ---------------------------------------------------------------------------


def _make_s3_mock(payload) -> MagicMock:
    """Cria um cliente S3 simulado que retorna `payload` serializado como JSON."""
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode()
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {"Body": body}
    return s3_mock


# ---------------------------------------------------------------------------
# _fetch_tmdb_detail
# ---------------------------------------------------------------------------


def _make_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


class TestFetchTmdbDetail:
    def test_returns_ptbr_overview_when_present(self):
        detail_ptbr = {"id": 1, "overview": "Sinopse em português", "runtime": 120}
        with patch("src.utils.requests.get", return_value=_make_response(detail_ptbr)) as mock_get:
            result = _fetch_tmdb_detail("key", "movie", 1)
            assert result["overview"] == "Sinopse em português"
            assert mock_get.call_count == 1

    def test_falls_back_to_english_when_ptbr_overview_is_empty(self):
        detail_ptbr = {"id": 2, "overview": "", "runtime": 90}
        detail_en = {"id": 2, "overview": "English synopsis", "runtime": 90}
        responses = [_make_response(detail_ptbr), _make_response(detail_en)]
        with patch("src.utils.requests.get", side_effect=responses) as mock_get:
            result = _fetch_tmdb_detail("key", "movie", 2)
            assert result["overview"] == "English synopsis"
            assert mock_get.call_count == 2
            assert mock_get.call_args_list[1][1]["params"]["language"] == "en-US"

    def test_falls_back_to_english_when_ptbr_overview_is_whitespace(self):
        detail_ptbr = {"id": 3, "overview": "   ", "runtime": 60}
        detail_en = {"id": 3, "overview": "English synopsis", "runtime": 60}
        with patch("src.utils.requests.get", side_effect=[_make_response(detail_ptbr), _make_response(detail_en)]):
            result = _fetch_tmdb_detail("key", "tv", 3)
            assert result["overview"] == "English synopsis"

    def test_no_second_call_when_ptbr_overview_is_present(self):
        detail_ptbr = {"id": 4, "overview": "Sinopse", "runtime": 45}
        with patch("src.utils.requests.get", return_value=_make_response(detail_ptbr)) as mock_get:
            _fetch_tmdb_detail("key", "tv", 4)
            assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# enrich_with_runtime
# ---------------------------------------------------------------------------


class TestEnrichWithRuntime:
    def test_movie_runtime_is_set(self):
        df = pd.DataFrame([{"id": 1, "overview": "Sinopse"}])
        detail = {"overview": "Sinopse", "runtime": 120}
        with patch("src.utils._fetch_tmdb_detail", return_value=detail):
            result = enrich_with_runtime(df, "key", "movie")
            assert result["runtime"].iloc[0] == 120

    def test_movie_overview_fallback_applied_when_empty(self):
        df = pd.DataFrame([{"id": 1, "overview": ""}])
        detail = {"overview": "English synopsis", "runtime": 90}
        with patch("src.utils._fetch_tmdb_detail", return_value=detail):
            result = enrich_with_runtime(df, "key", "movie")
            assert result["overview"].iloc[0] == "English synopsis"

    def test_movie_overview_not_overwritten_when_present(self):
        df = pd.DataFrame([{"id": 1, "overview": "Sinopse original"}])
        detail = {"overview": "Sinopse original", "runtime": 90}
        with patch("src.utils._fetch_tmdb_detail", return_value=detail):
            result = enrich_with_runtime(df, "key", "movie")
            assert result["overview"].iloc[0] == "Sinopse original"

    def test_tv_episode_fields_are_set(self):
        df = pd.DataFrame([{"id": 10, "overview": "Sinopse"}])
        detail = {"overview": "Sinopse", "episode_run_time": [45], "number_of_seasons": 3, "number_of_episodes": 30}
        with patch("src.utils._fetch_tmdb_detail", return_value=detail):
            result = enrich_with_runtime(df, "key", "tv")
            assert result["number_of_seasons"].iloc[0] == 3
            assert result["number_of_episodes"].iloc[0] == 30

    def test_failed_detail_call_sets_runtime_to_none(self):
        df = pd.DataFrame([{"id": 99, "overview": "Sinopse"}])
        with patch("src.utils._fetch_tmdb_detail", side_effect=Exception("timeout")):
            result = enrich_with_runtime(df, "key", "movie")
            assert result["runtime"].iloc[0] is None


# ---------------------------------------------------------------------------
# read_from_sor — table_type="discover"
# ---------------------------------------------------------------------------


class TestReadFromSorDiscover:
    def test_calls_wrangler_with_correct_path(self):
        df_mock = pd.DataFrame(
            [{"id": 1, "title": "Film A"}, {"id": 2, "title": "Film B"}]
        )
        with patch("awswrangler.s3.read_json", return_value=df_mock) as mock_read:
            read_from_sor("my-sor", "movie", "discover", year="2023")
            mock_read.assert_called_once_with(
                path="s3://my-sor/tmdb/discover/movie/ano=2023/",
                orient="records",
            )

    def test_adds_year_column(self):
        df_mock = pd.DataFrame([{"id": 1, "title": "Film A"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2023")
            assert "year" in result.columns
            assert result["year"].iloc[0] == "2023"

    def test_year_column_value_matches_arg(self):
        df_mock = pd.DataFrame([{"id": 1}, {"id": 2}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2000")
            assert (result["year"] == "2000").all()

    def test_tv_uses_correct_path(self):
        df_mock = pd.DataFrame([{"id": 10, "name": "Serie A"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock) as mock_read:
            read_from_sor("my-sor", "tv", "discover", year="2022")
            mock_read.assert_called_once_with(
                path="s3://my-sor/tmdb/discover/tv/ano=2022/",
                orient="records",
            )


# ---------------------------------------------------------------------------
# read_from_sor — table_type="genre"
# ---------------------------------------------------------------------------


class TestReadFromSorGenre:
    def test_movie_reads_correct_s3_key(self):
        s3_mock = _make_s3_mock([{"id": 28, "name": "Ação"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "movie", "genre")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/genre/movie/generos_filmes.json",
            )

    def test_tv_reads_correct_s3_key(self):
        s3_mock = _make_s3_mock([{"id": 10759, "name": "Ação & Aventura"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "tv", "genre")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/genre/tv/generos_series.json",
            )

    def test_returns_dataframe_from_list(self):
        genres = [{"id": 28, "name": "Ação"}, {"id": 12, "name": "Aventura"}]
        s3_mock = _make_s3_mock(genres)
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "genre")
            assert len(result) == 2
            assert list(result.columns) == ["id", "name"]
            assert result["id"].tolist() == [28, 12]


# ---------------------------------------------------------------------------
# read_from_sor — table_type="configuration"
# ---------------------------------------------------------------------------


class TestReadFromSorConfiguration:
    def test_movie_reads_languages_s3_key(self):
        s3_mock = _make_s3_mock([{"iso_639_1": "pt", "english_name": "Portuguese"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "movie", "configuration")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/configuration/languages/idiomas.json",
            )

    def test_tv_reads_countries_s3_key(self):
        s3_mock = _make_s3_mock([{"iso_3166_1": "BR", "english_name": "Brazil"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "tv", "configuration")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/configuration/countries/paises.json",
            )

    def test_returns_dataframe_from_list(self):
        s3_mock = _make_s3_mock([{"iso_639_1": "pt"}, {"iso_639_1": "en"}])
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "configuration")
            assert len(result) == 2
            assert "iso_639_1" in result.columns


# ---------------------------------------------------------------------------
# write_parquet_to_sot
# ---------------------------------------------------------------------------


class TestWriteParquetToSot:
    def test_with_partition_cols(self):
        df = pd.DataFrame([{"id": 1, "year": "2023"}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_discover_movie_tmdb",
                database="db_tmdb",
                partition_cols=["year"],
            )
            mock_write.assert_called_once_with(
                df=df,
                path="s3://my-sot/tmdb/tb_discover_movie_tmdb/",
                dataset=True,
                partition_cols=["year"],
                mode="overwrite_partitions",
                database="db_tmdb",
                table="tb_discover_movie_tmdb",
            )

    def test_without_partition_cols_defaults_to_none(self):
        df = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_genre_movie_tmdb",
                database="db_tmdb",
            )
            mock_write.assert_called_once_with(
                df=df,
                path="s3://my-sot/tmdb/tb_genre_movie_tmdb/",
                dataset=True,
                partition_cols=None,
                mode="overwrite_partitions",
                database="db_tmdb",
                table="tb_genre_movie_tmdb",
            )

    def test_custom_mode_is_forwarded(self):
        df = pd.DataFrame([{"id": 1}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_test",
                database="db_tmdb",
                mode="overwrite",
            )
            _, kwargs = mock_write.call_args
            assert kwargs["mode"] == "overwrite"

    def test_s3_path_uses_table_name(self):
        df = pd.DataFrame([{"id": 1}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="bucket-sot",
                table_name="tb_custom",
                database="db_tmdb",
            )
            _, kwargs = mock_write.call_args
            assert kwargs["path"] == "s3://bucket-sot/tmdb/tb_custom/"


# ---------------------------------------------------------------------------
# trigger_data_quality
# ---------------------------------------------------------------------------


class TestTriggerDataQuality:
    def _make_glue_mock(self, run_id="run-123") -> MagicMock:
        glue_mock = MagicMock()
        glue_mock.start_job_run.return_value = {"JobRunId": run_id}
        return glue_mock

    def test_calls_start_job_run_with_correct_args(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_data_quality("dq-job", "tb_genre_movie_tmdb", "db_tmdb")
            glue_mock.start_job_run.assert_called_once_with(
                JobName="dq-job",
                Arguments={
                    "--TABLE_NAME": "tb_genre_movie_tmdb",
                    "--DATABASE": "db_tmdb",
                },
            )

    def test_includes_year_when_provided(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_data_quality(
                "dq-job", "tb_discover_movie_tmdb", "db_tmdb", year="2023"
            )
            _, kwargs = glue_mock.start_job_run.call_args
            assert kwargs["Arguments"]["--YEAR"] == "2023"

    def test_omits_year_when_not_provided(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_data_quality("dq-job", "tb_genre_movie_tmdb", "db_tmdb")
            _, kwargs = glue_mock.start_job_run.call_args
            assert "--YEAR" not in kwargs["Arguments"]

    def test_returns_job_run_id(self):
        glue_mock = self._make_glue_mock(run_id="run-abc")
        with patch("boto3.client", return_value=glue_mock):
            run_id = trigger_data_quality("dq-job", "tb_genre_movie_tmdb", "db_tmdb")
            assert run_id == "run-abc"
