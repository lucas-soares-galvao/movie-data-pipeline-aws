"""Testes unitários para app/glue_details/src/utils.py."""

from unittest.mock import MagicMock, patch

import src.utils as u


# ---------------------------------------------------------------------------
# fetch_tmdb_details
# ---------------------------------------------------------------------------


class TestFetchTmdbDetails:
    def test_calls_movie_endpoint(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 1, "runtime": 120}
        with patch("src.utils.requests.get", return_value=mock_response) as mock_get:
            u.fetch_tmdb_details("key-123", "movie", 1)
            url = mock_get.call_args[0][0]
            assert "/movie/1" in url

    def test_calls_tv_endpoint(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 10,
            "number_of_seasons": 3,
            "number_of_episodes": 36,
            "episode_run_time": [45],
        }
        with patch("src.utils.requests.get", return_value=mock_response) as mock_get:
            u.fetch_tmdb_details("key-123", "tv", 10)
            url = mock_get.call_args[0][0]
            assert "/tv/10" in url

    def test_returns_json_response(self):
        expected = {"id": 1, "runtime": 90}
        mock_response = MagicMock()
        mock_response.json.return_value = expected
        with patch("src.utils.requests.get", return_value=mock_response):
            result = u.fetch_tmdb_details("key-123", "movie", 1)
            assert result == expected


# ---------------------------------------------------------------------------
# collect_and_write_details
# ---------------------------------------------------------------------------


class TestCollectAndWriteDetails:
    def _mock_movie_response(self, item_id: int) -> dict:
        return {"id": item_id, "runtime": 100, "release_date": "2023-05-10"}

    def _mock_tv_response(self, item_id: int) -> dict:
        return {
            "id": item_id,
            "number_of_seasons": 2,
            "number_of_episodes": 20,
            "episode_run_time": [45],
            "first_air_date": "2022-03-01",
        }

    def test_movie_writes_runtime_and_year(self):
        ids = [1, 2]
        responses = [self._mock_movie_response(i) for i in ids]

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=responses),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", ids, "movie", "sot", "tb_details_movie_tmdb", "db")
            df_written = mock_write.call_args.kwargs["df"]

            assert "id" in df_written.columns
            assert "runtime" in df_written.columns
            assert "year" in df_written.columns
            assert len(df_written) == 2

    def test_tv_writes_seasons_episodes_runtime(self):
        ids = [10, 20]
        responses = [self._mock_tv_response(i) for i in ids]

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=responses),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", ids, "tv", "sot", "tb_details_tv_tmdb", "db")
            df_written = mock_write.call_args.kwargs["df"]

            assert "number_of_seasons" in df_written.columns
            assert "number_of_episodes" in df_written.columns
            assert "episode_run_time" in df_written.columns

    def test_skips_failed_ids_without_raising(self):
        import requests as req_lib

        responses = [
            req_lib.RequestException("timeout"),
            {"id": 2, "runtime": 90, "release_date": "2023-01-01"},
        ]

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=responses),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1, 2], "movie", "sot", "tb_details_movie_tmdb", "db")
            df_written = mock_write.call_args.kwargs["df"]
            # ID 1 falhou, apenas ID 2 deve estar no DataFrame
            assert len(df_written) == 1
            assert df_written.iloc[0]["id"] == 2

    def test_does_not_write_when_all_ids_fail(self):
        import requests as req_lib

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=req_lib.RequestException("err")),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_details_movie_tmdb", "db")
            mock_write.assert_not_called()

    def test_writes_with_year_partition(self):
        responses = [self._mock_movie_response(1)]

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=responses),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1], "movie", "sot", "tb_details_movie_tmdb", "db")
            assert mock_write.call_args.kwargs["partition_cols"] == ["year"]


# ---------------------------------------------------------------------------
# trigger_agg
# ---------------------------------------------------------------------------


class TestTriggerAgg:
    def test_starts_agg_job(self):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr-123"}

        with patch("src.utils.boto3.client", return_value=mock_glue):
            run_id = u.trigger_agg("agg-job")

        mock_glue.start_job_run.assert_called_once_with(JobName="agg-job")
        assert run_id == "jr-123"
