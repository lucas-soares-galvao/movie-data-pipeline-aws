from unittest.mock import patch

import pandas as pd

import main as m

_BASE_ARGS = {
    "S3_BUCKET_SPEC": "my-spec",
    "S3_PREFIX_SPEC": "my-prefix",
    "S3_BUCKET_TEMP": "my-temp",
    "DB_MOVIE":   "db_movie_tmdb",
    "DB_TV":      "db_tv_tmdb",
    "DB_UNIFIED": "db_unified_tmdb",
    "TABLE_NAME": "tb_discover_unified_tmdb",
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "ENVIRONMENT": "dev",
}

_DF_MOCK = pd.DataFrame(
    [
        {"id": 1, "media_type": "movie", "title": "Film A", "year": "2023"},
        {"id": 2, "media_type": "tv", "title": "Show B", "year": "2022"},
    ]
)


class TestMain:
    def test_calls_run_athena_query_with_correct_args(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK) as mock_query,
            patch.object(m, "write_parquet_to_spec"),
            patch.object(m, "trigger_data_quality"),
        ):
            m.main()
            mock_query.assert_called_once_with(
                db_movie="db_movie_tmdb",
                db_tv="db_tv_tmdb",
                db_unified="db_unified_tmdb",
                s3_bucket_temp="my-temp",
                env="dev",
            )

    def test_calls_write_parquet_to_spec_with_correct_args(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "write_parquet_to_spec") as mock_write,
            patch.object(m, "trigger_data_quality"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=_DF_MOCK,
                s3_bucket_spec="my-spec",
                s3_prefix_spec="my-prefix",
                table_name="tb_discover_unified_tmdb",
                database="db_unified_tmdb",
            )

    def test_write_receives_dataframe_returned_by_query(self):
        df_custom = pd.DataFrame([{"id": 99, "media_type": "movie", "year": "2024"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=df_custom),
            patch.object(m, "write_parquet_to_spec") as mock_write,
            patch.object(m, "trigger_data_quality"),
        ):
            m.main()
            actual_df = mock_write.call_args.kwargs["df"]
            pd.testing.assert_frame_equal(actual_df, df_custom)

    def test_pipeline_runs_without_exceptions(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "write_parquet_to_spec"),
            patch.object(m, "trigger_data_quality"),
        ):
            m.main()

    def test_write_called_exactly_once(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "write_parquet_to_spec") as mock_write,
            patch.object(m, "trigger_data_quality"),
        ):
            m.main()
            assert mock_write.call_count == 1

    def test_query_called_exactly_once(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK) as mock_query,
            patch.object(m, "write_parquet_to_spec"),
            patch.object(m, "trigger_data_quality"),
        ):
            m.main()
            assert mock_query.call_count == 1

    def test_dataframe_vazio_nao_escreve_mas_aciona_dq(self):
        df_vazio = pd.DataFrame()
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=df_vazio),
            patch.object(m, "write_parquet_to_spec") as mock_write,
            patch.object(m, "trigger_data_quality") as mock_dq,
        ):
            m.main()
            mock_write.assert_called_once()
            mock_dq.assert_called_once()

    def test_aciona_dq_apos_escrita_sem_year(self):
        # call_order rastreia a sequência real de execução das funções.
        # side_effect=lambda **_: ... substitui a função real por uma que apenas
        # registra a chamada na lista — "**_" significa "aceita quaisquer kwargs mas ignora todos".
        call_order = []
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "write_parquet_to_spec", side_effect=lambda **_: call_order.append("write")),
            patch.object(m, "trigger_data_quality", side_effect=lambda **_: call_order.append("dq")) as mock_dq,
        ):
            m.main()
        mock_dq.assert_called_once_with(
            dq_job_name="dq-job",
            table_name="tb_discover_unified_tmdb",
            database="db_unified_tmdb",
        )
        assert call_order == ["write", "dq"]

