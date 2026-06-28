from unittest.mock import call, patch

import main as m

_BASE = {
    "S3_BUCKET_SOT": "my-sot",
    "S3_BUCKET_TEMP": "my-temp",
    "DATABASE": "db_tmdb_movie_dev",
    "TABLE_DISCOVER_MOVIE": "tb_tmdb_discover_movie_dev",
    "TABLE_DISCOVER_TV": "tb_tmdb_discover_tv_dev",
    "TABLE_DETAILS_MOVIE": "tb_tmdb_details_movie_dev",
    "TABLE_DETAILS_TV": "tb_tmdb_details_tv_dev",
    "TABLE_WATCH_PROVIDERS_MOVIE": "tb_tmdb_watch_providers_movie_dev",
    "TABLE_WATCH_PROVIDERS_TV": "tb_tmdb_watch_providers_tv_dev",
    "TMDB_SECRET_ARN": "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb",
    "GLUE_AGG_JOB_NAME": "agg-job",
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "MEDIA_TYPE": "movie",
    "YEAR": "2025",
    "END_YEAR": "2025",
    "FORCE_REFETCH": False,
}

_IDS = [1, 2]


def _base_patches(args=None, existing_ids=None, stale_ids=None):
    """Retorna context managers base para todos os testes de main()."""
    return (
        patch.object(m, "get_parameters_glue", return_value=args or _BASE),
        patch.object(m, "get_api_secret", return_value="key-123"),
        patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
        patch.object(m, "fetch_existing_ids_from_details", return_value=existing_ids if existing_ids is not None else []),
        patch.object(m, "fetch_ids_stale_watch_providers", return_value=stale_ids if stale_ids is not None else _IDS),
        patch.object(m, "collect_and_write_details"),
        patch.object(m, "collect_and_write_watch_providers"),
        patch.object(m, "trigger_glue_job"),
        patch.object(m, "repair_discover_duplicates"),
        patch.object(m, "repair_watch_providers_duplicates"),
        patch.object(m, "repair_details_duplicates"),
    )


class TestMain:
    def test_fetches_api_key_from_secrets_manager(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123") as mock_key,
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_key.assert_called_once_with(
                "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb", "tmdb_api_key"
            )

    def test_fetches_ids_for_movie_using_discover_movie_table(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS) as mock_ids,
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_ids.assert_called_once_with(
                database="db_tmdb_movie_dev",
                table_discover="tb_tmdb_discover_movie_dev",
                s3_bucket_temp="my-temp",
                year="2025",
            )

    def test_fetches_ids_for_tv_using_discover_tv_table(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS) as mock_ids,
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_ids.assert_called_once_with(
                database="db_tmdb_movie_dev",
                table_discover="tb_tmdb_discover_tv_dev",
                s3_bucket_temp="my-temp",
                year="2024",
            )

    def test_collect_called_once_for_movie(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            assert mock_collect.call_count == 1
            call_kw = mock_collect.call_args
            assert call_kw.kwargs["content_type"] == "movie"
            assert set(call_kw.kwargs["ids"]) == set(_IDS)
            assert call_kw.kwargs["table_name"] == "tb_tmdb_details_movie_dev"

    def test_collect_watch_providers_called_with_correct_args_for_movie(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers") as mock_wp,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_wp.assert_called_once()
            call_kw = mock_wp.call_args
            assert call_kw.kwargs["content_type"] == "movie"
            assert call_kw.kwargs["ids"] == _IDS
            assert call_kw.kwargs["table_name"] == "tb_tmdb_watch_providers_movie_dev"
            assert call_kw.kwargs["year"] == "2025"

    def test_collect_watch_providers_called_with_correct_args_for_tv(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers") as mock_wp,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_wp.assert_called_once()
            call_kw = mock_wp.call_args
            assert call_kw.kwargs["content_type"] == "tv"
            assert call_kw.kwargs["table_name"] == "tb_tmdb_watch_providers_tv_dev"
            assert call_kw.kwargs["year"] == "2024"

    def test_triggers_data_quality_twice_for_details_and_watch_providers(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            dq_calls = [c for c in mock_trigger.call_args_list if c.args[0] == "dq-job"]
            assert len(dq_calls) == 2
            assert call("dq-job", TABLE_NAME="tb_tmdb_details_movie_dev", DATABASE="db_tmdb_movie_dev", YEAR="2025") in dq_calls
            assert call("dq-job", TABLE_NAME="tb_tmdb_watch_providers_movie_dev", DATABASE="db_tmdb_movie_dev", YEAR="2025") in dq_calls

    def test_collect_called_once_for_tv(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            assert mock_collect.call_count == 1
            call_kw = mock_collect.call_args
            assert call_kw.kwargs["content_type"] == "tv"
            assert set(call_kw.kwargs["ids"]) == set(_IDS)
            assert call_kw.kwargs["table_name"] == "tb_tmdb_details_tv_dev"

    def test_triggers_agg_when_tv_and_last_year(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2025", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
            patch.object(m, "repair_details_duplicates"),
        ):
            m.main()
            agg_calls = [c for c in mock_trigger.call_args_list if c.args[0] == "agg-job"]
            assert len(agg_calls) == 1
            assert agg_calls[0] == call("agg-job")

    def test_repair_called_before_agg_when_tv_and_last_year(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2025", "END_YEAR": "2025"}
        call_order = []
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job", side_effect=lambda *a, **kw: call_order.append("agg") if not kw else None),
            patch.object(m, "repair_discover_duplicates", side_effect=lambda **_: call_order.append("repair_discover")),
            patch.object(m, "repair_watch_providers_duplicates", side_effect=lambda **_: call_order.append("repair_wp")),
            patch.object(m, "repair_details_duplicates", side_effect=lambda **_: call_order.append("repair_details")) as mock_repair,
        ):
            m.main()
        mock_repair.assert_called_once_with(
            database="db_tmdb_movie_dev",
            table_details="tb_tmdb_details_tv_dev",
            s3_bucket_sot="my-sot",
            s3_bucket_temp="my-temp",
            year="2025",
        )
        assert call_order == ["repair_discover", "repair_wp", "repair_details", "agg"]

    def test_repair_called_for_movie_at_last_year(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
            patch.object(m, "repair_details_duplicates") as mock_repair,
        ):
            m.main()
            mock_repair.assert_called_once_with(
                database="db_tmdb_movie_dev",
                table_details="tb_tmdb_details_movie_dev",
                s3_bucket_sot="my-sot",
                s3_bucket_temp="my-temp",
                year="2025",
            )

    def test_repair_not_called_when_not_last_year(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
            patch.object(m, "repair_discover_duplicates") as mock_repair_discover,
            patch.object(m, "repair_watch_providers_duplicates") as mock_repair_wp,
            patch.object(m, "repair_details_duplicates") as mock_repair_details,
        ):
            m.main()
            mock_repair_discover.assert_not_called()
            mock_repair_wp.assert_not_called()
            mock_repair_details.assert_not_called()

    def test_does_not_trigger_agg_for_movie(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
            patch.object(m, "repair_details_duplicates"),
        ):
            m.main()
            agg_calls = [c for c in mock_trigger.call_args_list if c.args[0] == "agg-job"]
            assert len(agg_calls) == 0

    def test_does_not_trigger_agg_for_tv_non_last_year(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job") as mock_trigger,
            patch.object(m, "repair_details_duplicates"),
        ):
            m.main()
            agg_calls = [c for c in mock_trigger.call_args_list if c.args[0] == "agg-job"]
            assert len(agg_calls) == 0

    def test_skip_collect_details_when_no_new_ids(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=_IDS),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_collect.assert_not_called()

    def test_skip_collect_watch_providers_when_no_stale_ids(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=[]),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers") as mock_wp,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_wp.assert_not_called()

    def test_repair_discover_duplicates_called_at_last_year(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
            patch.object(m, "repair_discover_duplicates") as mock_repair_discover,
            patch.object(m, "repair_watch_providers_duplicates"),
            patch.object(m, "repair_details_duplicates"),
        ):
            m.main()
            mock_repair_discover.assert_called_once_with(
                database="db_tmdb_movie_dev",
                table_discover="tb_tmdb_discover_movie_dev",
                s3_bucket_sot="my-sot",
                year="2025",
            )

    def test_force_refetch_skips_existing_ids_check(self):
        args = {**_BASE, "FORCE_REFETCH": True}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details") as mock_existing,
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details") as mock_collect,
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
            patch.object(m, "repair_details_duplicates"),
        ):
            m.main()
            mock_existing.assert_not_called()
            assert set(mock_collect.call_args.kwargs["ids"]) == set(_IDS)

    def test_repair_watch_providers_duplicates_called_at_last_year(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_sot", return_value=_IDS),
            patch.object(m, "fetch_existing_ids_from_details", return_value=[]),
            patch.object(m, "fetch_ids_stale_watch_providers", return_value=_IDS),
            patch.object(m, "collect_and_write_details"),
            patch.object(m, "collect_and_write_watch_providers"),
            patch.object(m, "trigger_glue_job"),
            patch.object(m, "repair_discover_duplicates"),
            patch.object(m, "repair_watch_providers_duplicates") as mock_repair_wp,
            patch.object(m, "repair_details_duplicates"),
        ):
            m.main()
            mock_repair_wp.assert_called_once_with(
                database="db_tmdb_movie_dev",
                table_watch_providers="tb_tmdb_watch_providers_movie_dev",
                s3_bucket_sot="my-sot",
                year="2025",
            )
