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
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "MEDIA_TYPE": "movie",
    "YEAR": "2025",
    "END_YEAR": "2025",
    "FORCE_REFETCH": False,
    "TRANSLATE_PROVIDER": "aws",
    "CHANGES_S3_PATH": None,
}


class TestMain:
    """main() só resolve argumentos, busca a API key e delega para
    run_details_and_watch_providers_for_year — a lógica de negócio (delta,
    coleta, DQ por unidade, repair de duplicatas) é testada em
    test_utils.py::TestRunDetailsAndWatchProvidersForYear."""

    def test_fetches_api_key_from_secrets_manager(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123") as mock_key,
            patch.object(m, "run_details_and_watch_providers_for_year"),
        ):
            m.main()
            mock_key.assert_called_once_with(
                "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb", "tmdb_api_key"
            )

    def test_delegates_to_run_details_and_watch_providers_for_year_for_movie(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "run_details_and_watch_providers_for_year") as mock_run,
        ):
            m.main()
            mock_run.assert_called_once_with(
                api_key="key-123",
                database="db_tmdb_movie_dev",
                media_type="movie",
                year="2025",
                end_year="2025",
                s3_bucket_sot="my-sot",
                s3_bucket_temp="my-temp",
                table_discover="tb_tmdb_discover_movie_dev",
                table_details="tb_tmdb_details_movie_dev",
                table_watch_providers="tb_tmdb_watch_providers_movie_dev",
                dq_job_name="dq-job",
                force_refetch=False,
                translate_provider="aws",
            )

    def test_delegates_to_run_details_and_watch_providers_for_year_for_tv(self):
        args = {**_BASE, "MEDIA_TYPE": "tv", "YEAR": "2024", "END_YEAR": "2025"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "run_details_and_watch_providers_for_year") as mock_run,
        ):
            m.main()
            mock_run.assert_called_once_with(
                api_key="key-123",
                database="db_tmdb_movie_dev",
                media_type="tv",
                year="2024",
                end_year="2025",
                s3_bucket_sot="my-sot",
                s3_bucket_temp="my-temp",
                table_discover="tb_tmdb_discover_tv_dev",
                table_details="tb_tmdb_details_tv_dev",
                table_watch_providers="tb_tmdb_watch_providers_tv_dev",
                dq_job_name="dq-job",
                force_refetch=False,
                translate_provider="aws",
            )

    def test_force_refetch_passed_through(self):
        args = {**_BASE, "FORCE_REFETCH": True}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "run_details_and_watch_providers_for_year") as mock_run,
        ):
            m.main()
            assert mock_run.call_args.kwargs["force_refetch"] is True

    def test_does_not_pass_trigger_dq_explicitly(self):
        """main() não informa trigger_dq — usa o default True da função
        (caminho de produção via job Glue continua disparando o DQ por unidade)."""
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "run_details_and_watch_providers_for_year") as mock_run,
        ):
            m.main()
            assert "trigger_dq" not in mock_run.call_args.kwargs


_BASE_CHANGES = {
    **_BASE,
    "CHANGES_S3_PATH": "s3://my-temp/tmdb/changes/movie/2026-07-08.json",
}


class TestChangesMode:
    """Testa o ramo acionado quando CHANGES_S3_PATH está presente (modo changes)."""

    def test_entra_no_ramo_changes_e_nao_chama_run_details_and_watch_providers(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_CHANGES),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_changes_file", return_value=[10, 20]),
            patch.object(m, "process_changed_ids", return_value=["2020", "2021"]),
            patch.object(m, "trigger_glue_job"),
            patch.object(m, "run_details_and_watch_providers_for_year") as mock_run,
        ):
            m.main()
            mock_run.assert_not_called()

    def test_chama_fetch_ids_from_changes_file_com_o_path_correto(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_CHANGES),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_changes_file", return_value=[10, 20]) as mock_fetch,
            patch.object(m, "process_changed_ids", return_value=[]),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_fetch.assert_called_once_with("s3://my-temp/tmdb/changes/movie/2026-07-08.json")

    def test_chama_process_changed_ids_com_ids_e_tabelas_corretas(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_CHANGES),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_changes_file", return_value=[10, 20]),
            patch.object(m, "process_changed_ids", return_value=[]) as mock_process,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_process.assert_called_once_with(
                api_key="key-123",
                database="db_tmdb_movie_dev",
                table_discover="tb_tmdb_discover_movie_dev",
                table_details="tb_tmdb_details_movie_dev",
                table_watch_providers="tb_tmdb_watch_providers_movie_dev",
                content_type="movie",
                changed_ids=[10, 20],
                s3_bucket_sot="my-sot",
                s3_bucket_temp="my-temp",
                translate_provider="aws",
            )

    def test_aciona_dq_uma_vez_por_tabela_com_anos_agrupados(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_CHANGES),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_changes_file", return_value=[10, 20]),
            patch.object(m, "process_changed_ids", return_value=["2020", "2021"]),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            dq_calls = [c for c in mock_trigger.call_args_list if c.args[0] == "dq-job"]
            assert len(dq_calls) == 2
            assert call("dq-job", TABLE_NAME="tb_tmdb_details_movie_dev", DATABASE="db_tmdb_movie_dev", YEAR="2020,2021") in dq_calls
            assert call("dq-job", TABLE_NAME="tb_tmdb_watch_providers_movie_dev", DATABASE="db_tmdb_movie_dev", YEAR="2020,2021") in dq_calls

    def test_nao_aciona_dq_quando_nenhum_ano_afetado(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_CHANGES),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_changes_file", return_value=[]),
            patch.object(m, "process_changed_ids", return_value=[]),
            patch.object(m, "trigger_glue_job") as mock_trigger,
        ):
            m.main()
            mock_trigger.assert_not_called()

    def test_usa_tabelas_de_tv_quando_media_type_tv(self):
        args = {**_BASE_CHANGES, "MEDIA_TYPE": "tv"}
        with (
            patch.object(m, "get_parameters_glue", return_value=args),
            patch.object(m, "get_api_secret", return_value="key-123"),
            patch.object(m, "fetch_ids_from_changes_file", return_value=[10, 20]),
            patch.object(m, "process_changed_ids", return_value=[]) as mock_process,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            assert mock_process.call_args.kwargs["table_discover"] == "tb_tmdb_discover_tv_dev"
            assert mock_process.call_args.kwargs["table_details"] == "tb_tmdb_details_tv_dev"
            assert mock_process.call_args.kwargs["table_watch_providers"] == "tb_tmdb_watch_providers_tv_dev"
            assert mock_process.call_args.kwargs["content_type"] == "tv"
