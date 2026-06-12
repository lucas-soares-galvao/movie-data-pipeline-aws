import pandas as pd
import pytest
import requests
from unittest.mock import MagicMock, patch

import src.utils as u


# ---------------------------------------------------------------------------
# _tmdb_get
# ---------------------------------------------------------------------------


def _make_response(status_code=200, json_data=None, headers=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.headers = headers or {}
    r.raise_for_status.return_value = None
    return r


class TestTmdbGet:
    def test_retorna_json_em_sucesso(self):
        with patch("src.utils.requests.get", return_value=_make_response(200, {"ok": True})), \
             patch("src.utils.time.sleep") as mock_sleep:
            result = u._tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        assert result == {"ok": True}
        mock_sleep.assert_not_called()

    def test_retry_em_status_transiente_e_retorna_em_sucesso(self):
        with patch("src.utils.requests.get", side_effect=[_make_response(500), _make_response(200, {"ok": True})]) as mock_get, \
             patch("src.utils.time.sleep") as mock_sleep:
            result = u._tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        assert result == {"ok": True}
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    def test_retry_em_429_usa_retry_after(self):
        with patch("src.utils.requests.get", side_effect=[
            _make_response(429, headers={"Retry-After": "5"}),
            _make_response(200, {}),
        ]), patch("src.utils.time.sleep") as mock_sleep:
            u._tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        wait = mock_sleep.call_args[0][0]
        assert wait >= 5

    def test_retry_em_connection_error_e_retorna_em_sucesso(self):
        with patch("src.utils.requests.get", side_effect=[
            requests.exceptions.ConnectionError("timeout"),
            _make_response(200, {"ok": True}),
        ]) as mock_get, patch("src.utils.time.sleep") as mock_sleep:
            result = u._tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        assert result == {"ok": True}
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    def test_levanta_apos_esgotar_tentativas_http(self):
        r500 = _make_response(500)
        r500.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        with patch("src.utils.requests.get", return_value=r500) as mock_get, \
             patch("src.utils.time.sleep"):
            with pytest.raises(requests.exceptions.HTTPError):
                u._tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        assert mock_get.call_count == 3

    def test_levanta_apos_esgotar_tentativas_connection(self):
        with patch("src.utils.requests.get", side_effect=requests.exceptions.ConnectionError("fail")) as mock_get, \
             patch("src.utils.time.sleep"):
            with pytest.raises(requests.exceptions.ConnectionError):
                u._tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        assert mock_get.call_count == 3


# ---------------------------------------------------------------------------
# fetch_ids_from_sot
# ---------------------------------------------------------------------------


class TestFetchIdsFromSot:
    def _run(self, year="2025", ids=None, table="tb_discover_movie_tmdb"):
        df = pd.DataFrame({"id": ids or [1, 2]})
        with patch("src.utils.wr.athena.read_sql_query", return_value=df) as mock_athena:
            result = u.fetch_ids_from_sot(
                database="db_tmdb",
                table_discover=table,
                s3_bucket_temp="my-temp",
                year=year,
            )
        return result, mock_athena

    def test_sql_contains_year_equality_filter(self):
        _, mock_athena = self._run(year="2025")
        sql = mock_athena.call_args.kwargs["sql"]
        assert "WHERE year = '2025'" in sql

    def test_returns_list_of_ids(self):
        result, _ = self._run(ids=[1, 2])
        assert result == [1, 2]

    def test_year_filter_uses_passed_year(self):
        _, mock_athena = self._run(year="2000")
        sql = mock_athena.call_args.kwargs["sql"]
        assert "WHERE year = '2000'" in sql

    def test_queries_correct_table(self):
        _, mock_athena = self._run(table="tb_discover_tv_tmdb")
        sql = mock_athena.call_args.kwargs["sql"]
        assert "tb_discover_tv_tmdb" in sql


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
        return {
            "id": item_id,
            "runtime": 100,
            "release_date": "2023-05-10",
            "title": "Filme A",
            "overview": "Sinopse A",
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
        }

    def _mock_tv_response(self, item_id: int) -> dict:
        return {
            "id": item_id,
            "number_of_seasons": 2,
            "number_of_episodes": 20,
            "episode_run_time": [45],
            "first_air_date": "2022-03-01",
            "name": "Série A",
            "overview": "Sinopse A",
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
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
            assert "title_en" in df_written.columns
            assert "overview_en" in df_written.columns
            assert "poster_path_en" in df_written.columns
            assert "backdrop_path_en" in df_written.columns
            assert df_written.iloc[0]["title_en"] == "Filme A"
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
            assert "title_en" in df_written.columns
            assert "overview_en" in df_written.columns
            assert "poster_path_en" in df_written.columns
            assert "backdrop_path_en" in df_written.columns
            assert df_written.iloc[0]["title_en"] == "Série A"

    def test_skips_failed_ids_without_raising(self):
        import requests as req_lib

        # side_effect como função garante que ID 1 sempre falha e ID 2 sempre
        # tem sucesso, independente da ordem de execução das threads
        def side_effect(_key, _type, item_id):
            if item_id == 1:
                raise req_lib.RequestException("timeout")
            return {"id": 2, "runtime": 90, "release_date": "2023-01-01"}

        with (
            patch("src.utils.fetch_tmdb_details", side_effect=side_effect),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_details("key", [1, 2], "movie", "sot", "tb_details_movie_tmdb", "db")
            df_written = mock_write.call_args.kwargs["df"]
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
# fetch_tmdb_watch_providers
# ---------------------------------------------------------------------------


class TestFetchTmdbWatchProviders:
    def _make_response(self, br_data: dict) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": {"BR": br_data}}
        return mock_resp

    def test_calls_movie_watch_providers_endpoint(self):
        with patch("src.utils.requests.get", return_value=self._make_response({})) as mock_get:
            u.fetch_tmdb_watch_providers("key", "movie", 1)
            url = mock_get.call_args[0][0]
            assert "/movie/1/watch/providers" in url

    def test_calls_tv_watch_providers_endpoint(self):
        with patch("src.utils.requests.get", return_value=self._make_response({})) as mock_get:
            u.fetch_tmdb_watch_providers("key", "tv", 10)
            url = mock_get.call_args[0][0]
            assert "/tv/10/watch/providers" in url

    def test_returns_br_section(self):
        br = {"flatrate": [{"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"}]}
        with patch("src.utils.requests.get", return_value=self._make_response(br)):
            result = u.fetch_tmdb_watch_providers("key", "movie", 1)
            assert result == br


# ---------------------------------------------------------------------------
# _parse_watch_providers
# ---------------------------------------------------------------------------


class TestParseWatchProviders:
    def test_returns_empty_list_for_empty_br_data(self):
        assert u._parse_watch_providers({}, item_id=1, year="2025") == []

    def test_generates_one_record_per_flatrate_provider(self):
        br = {"flatrate": [
            {"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"},
            {"provider_name": "Prime",   "provider_id": 9, "logo_path": "/p.jpg"},
        ]}
        records = u._parse_watch_providers(br, item_id=1, year="2025")
        assert len(records) == 2
        assert records[0]["provider_type"] == "flatrate"
        assert records[0]["provider_name"] == "Netflix"
        assert records[0]["id"] == 1
        assert records[0]["year"] == "2025"

    def test_generates_records_for_multiple_provider_types(self):
        br = {
            "flatrate": [{"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"}],
            "rent":     [{"provider_name": "Apple",   "provider_id": 2, "logo_path": "/a.jpg"}],
            "buy":      [{"provider_name": "Google",  "provider_id": 3, "logo_path": "/g.jpg"}],
        }
        records = u._parse_watch_providers(br, item_id=5, year="2024")
        types = {r["provider_type"] for r in records}
        assert types == {"flatrate", "rent", "buy"}
        assert len(records) == 3

    def test_ignores_providers_without_name(self):
        br = {"flatrate": [
            {"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"},
            {"provider_id": 99, "logo_path": "/x.jpg"},  # sem provider_name
        ]}
        records = u._parse_watch_providers(br, item_id=1, year="2025")
        assert len(records) == 1
        assert records[0]["provider_name"] == "Netflix"


# ---------------------------------------------------------------------------
# collect_and_write_watch_providers
# ---------------------------------------------------------------------------


class TestCollectAndWriteWatchProviders:
    _BR_DATA = {
        "flatrate": [{"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"}]
    }

    def test_writes_records_with_year_partition(self):
        with (
            patch("src.utils.fetch_tmdb_watch_providers", return_value=self._BR_DATA),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_watch_providers("key", [1], "movie", "sot", "tb_wp_movie", "db", "2025")
            assert mock_write.call_args.kwargs["partition_cols"] == ["year"]

    def test_does_not_write_when_no_providers_found(self):
        with (
            patch("src.utils.fetch_tmdb_watch_providers", return_value={}),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_watch_providers("key", [1], "movie", "sot", "tb_wp_movie", "db", "2025")
            mock_write.assert_not_called()

    def test_skips_failed_ids_without_raising(self):
        import requests as req_lib

        def side_effect(_key, _type, item_id):
            if item_id == 1:
                raise req_lib.RequestException("timeout")
            return self._BR_DATA

        with (
            patch("src.utils.fetch_tmdb_watch_providers", side_effect=side_effect),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_watch_providers("key", [1, 2], "movie", "sot", "tb_wp_movie", "db", "2025")
            df_written = mock_write.call_args.kwargs["df"]
            assert len(df_written) == 1

    def test_passes_year_as_partition_value(self):
        with (
            patch("src.utils.fetch_tmdb_watch_providers", return_value=self._BR_DATA),
            patch("src.utils.wr.s3.to_parquet") as mock_write,
        ):
            u.collect_and_write_watch_providers("key", [1], "movie", "sot", "tb_wp_movie", "db", "2023")
            df_written = mock_write.call_args.kwargs["df"]
            assert df_written.iloc[0]["year"] == "2023"


# ---------------------------------------------------------------------------
# trigger_data_quality
# ---------------------------------------------------------------------------


class TestTriggerDataQuality:
    def test_starts_dq_job_with_table_database_and_year(self):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr-dq-1"}

        with patch("src.utils.boto3.client", return_value=mock_glue):
            run_id = u.trigger_data_quality("dq-job", "tb_details_movie_tmdb", "db_tmdb", "2025")

        mock_glue.start_job_run.assert_called_once_with(
            JobName="dq-job",
            Arguments={
                "--TABLE_NAME": "tb_details_movie_tmdb",
                "--DATABASE": "db_tmdb",
                "--YEAR": "2025",
            },
        )
        assert run_id == "jr-dq-1"

    def test_returns_job_run_id(self):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr-dq-99"}

        with patch("src.utils.boto3.client", return_value=mock_glue):
            run_id = u.trigger_data_quality("dq-job", "tb_watch_providers_movie_tmdb", "db_tmdb", "2024")

        assert run_id == "jr-dq-99"


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


# ---------------------------------------------------------------------------
# get_resolved_option / get_parameters_glue / get_tmdb_api_key
# ---------------------------------------------------------------------------


class TestGetResolvedOption:
    def test_delegates_to_getResolvedOptions(self):
        with patch("src.utils.getResolvedOptions", return_value={"DATABASE": "db"}) as mock_gro:
            result = u.get_resolved_option(["DATABASE"])
        mock_gro.assert_called_once()
        assert result == {"DATABASE": "db"}


class TestGetParametersGlue:
    def _required(self):
        return {
            "S3_BUCKET_SOT": "sot",
            "S3_BUCKET_TEMP": "tmp",
            "DATABASE": "db",
            "TABLE_DISCOVER_MOVIE": "tdm",
            "TABLE_DISCOVER_TV": "tdt",
            "TABLE_DETAILS_MOVIE": "det_m",
            "TABLE_DETAILS_TV": "det_tv",
            "TABLE_WATCH_PROVIDERS_MOVIE": "wp_m",
            "TABLE_WATCH_PROVIDERS_TV": "wp_tv",
            "TMDB_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:1:secret:tmdb",
            "GLUE_AGG_JOB_NAME": "agg-job",
            "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
            "MEDIA_TYPE": "movie",
            "YEAR": "2024",
            "END_YEAR": "2025",
        }

    def test_returns_all_required_args(self):
        with patch("src.utils.get_resolved_option", return_value=self._required()):
            result = u.get_parameters_glue()
        assert result["MEDIA_TYPE"] == "movie"
        assert result["YEAR"] == "2024"
        assert result["TMDB_SECRET_ARN"] == "arn:aws:secretsmanager:us-east-1:1:secret:tmdb"


class TestGetTmdbApiKey:
    def test_returns_api_key_from_secret(self):
        import json
        secret_value = json.dumps({"tmdb_api_key": "my-secret-key"})
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": secret_value}
        with patch("src.utils.boto3.client", return_value=mock_client):
            key = u.get_tmdb_api_key("arn:aws:secretsmanager:us-east-1:1:secret:tmdb")
        assert key == "my-secret-key"
