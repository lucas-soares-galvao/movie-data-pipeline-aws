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
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "MEDIA_TYPE": "movie",
    "YEAR": "2025",
    "END_YEAR": "2025",
}

_IDS = [1, 2]


class TestMain:
    def test_fetches_api_key_from_secrets_manager(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123") as mock_key,
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            mock_key.assert_called_once_with(
                "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb"
            )

    def test_fetches_ids_for_movie_using_discover_movie_table(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS) as mock_ids,
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            mock_ids.assert_called_once_with(
                database="db_tmdb",
                table_discover="tb_discover_movie_tmdb",
                s3_bucket_temp="my-temp",
                year="2025",
            )

    def test_fetches_ids_for_tv_using_discover_tv_table(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS) as mock_ids,
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            mock_ids.assert_called_once_with(
                database="db_tmdb",
                table_discover="tb_discover_tv_tmdb",
                s3_bucket_temp="my-temp",
                year="2024",
            )

    def test_collect_called_once_for_movie(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            assert mock_collect.call_count == 1
            call = mock_collect.call_args
            assert call.kwargs["content_type"] == "movie"
            assert call.kwargs["ids"] == _IDS
            assert call.kwargs["table_name"] == "tb_details_movie_tmdb"

    def test_triggers_data_quality_with_table_and_year(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_data_quality") as mock_dq,
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            mock_dq.assert_called_once_with(
                dq_job_name="dq-job",
                table_name="tb_details_movie_tmdb",
                database="db_tmdb",
                year="2025",
            )

    def test_collect_called_once_for_tv(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_agg"),
        ):
            m.main()
            assert mock_collect.call_count == 1
            call = mock_collect.call_args
            assert call.kwargs["content_type"] == "tv"
            assert call.kwargs["ids"] == _IDS
            assert call.kwargs["table_name"] == "tb_details_tv_tmdb"

    def test_triggers_agg_when_tv_and_last_year(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2025", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_agg") as mock_agg,
        ):
            m.main()
            mock_agg.assert_called_once_with(agg_job_name="agg-job")

    def test_does_not_trigger_agg_for_movie(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_agg") as mock_agg,
        ):
            m.main()
            mock_agg.assert_not_called()

    def test_does_not_trigger_agg_for_tv_non_last_year(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_tmdb_api_key", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "trigger_data_quality"),
            patch.object(m, "trigger_agg") as mock_agg,
        ):
            m.main()
            mock_agg.assert_not_called()
