"""Testes de integração para app/glue_details/main.py."""

from unittest.mock import patch

import main as m

_BASE = {
    "S3_BUCKET_SOT": "my-sot",
    "S3_BUCKET_TEMP": "my-temp",
    "DATABASE": "db_tmdb",
    "TABLE_DISCOVER_MOVIE": "tb_discover_movie_tmdb",
    "TABLE_DISCOVER_TV": "tb_discover_tv_tmdb",
    "TABLE_DETAILS_MOVIE": "tb_details_movie_tmdb",
    "TABLE_DETAILS_TV": "tb_details_tv_tmdb",
    "TMDB_SECRET_ARN": "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb",
    "GLUE_AGG_JOB_NAME": "agg-job",
}

_MOVIE_IDS = [1, 2]
_TV_IDS = [10, 20]


class TestMain:
    def test_fetches_api_key_from_secrets_manager(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123") as mock_key,
            patch.object(m, "fetch_ids_from_sot", return_value=(_MOVIE_IDS, _TV_IDS)),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            mock_key.assert_called_once_with(
                "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb"
            )

    def test_fetches_ids_from_sot(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(
                m, "fetch_ids_from_sot", return_value=(_MOVIE_IDS, _TV_IDS)
            ) as mock_ids,
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            mock_ids.assert_called_once_with(
                database="db_tmdb",
                table_discover_movie="tb_discover_movie_tmdb",
                table_discover_tv="tb_discover_tv_tmdb",
                s3_bucket_temp="my-temp",
            )

    def test_collects_movie_details(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=(_MOVIE_IDS, _TV_IDS)),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            first_call = mock_collect.call_args_list[0]
            assert first_call.kwargs["content_type"] == "movie"
            assert first_call.kwargs["ids"] == _MOVIE_IDS
            assert first_call.kwargs["table_name"] == "tb_details_movie_tmdb"

    def test_collects_tv_details(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=(_MOVIE_IDS, _TV_IDS)),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            second_call = mock_collect.call_args_list[1]
            assert second_call.kwargs["content_type"] == "tv"
            assert second_call.kwargs["ids"] == _TV_IDS
            assert second_call.kwargs["table_name"] == "tb_details_tv_tmdb"

    def test_collect_called_twice_movie_then_tv(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=(_MOVIE_IDS, _TV_IDS)),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            assert mock_collect.call_count == 2

    def test_triggers_agg_after_both_collections(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=(_MOVIE_IDS, _TV_IDS)),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_agg") as mock_agg,
        ):
            m.main()
            mock_agg.assert_called_once_with(agg_job_name="agg-job")
