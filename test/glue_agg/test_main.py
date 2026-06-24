from unittest.mock import patch

import pandas as pd

import main as m

_BASE_ARGS = {
    "S3_BUCKET_SPEC": "my-spec",
    "S3_PREFIX_SPEC": "my-prefix",
    "S3_BUCKET_TEMP": "my-temp",
    "DB_MOVIE":   "db_tmdb_movie_dev",
    "DB_TV":      "db_tmdb_tv_dev",
    "DB_UNIFIED": "db_tmdb_unified_dev",
    "TABLE_NAME": "tb_tmdb_discover_unified_dev",
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
        # patch.object substitui temporariamente uma função do módulo por um mock (objeto falso).
        # Isso permite testar main() sem chamar Athena, S3 ou Glue de verdade.
        # "as mock_query" captura o mock para inspecionar depois (ex: assert_called_once_with).
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK) as mock_query,
            patch.object(m, "write_parquet_to_spec"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_query.assert_called_once_with(
                db_movie="db_tmdb_movie_dev",
                db_tv="db_tmdb_tv_dev",
                db_unified="db_tmdb_unified_dev",
                s3_bucket_temp="my-temp",
                env="dev",
            )

    def test_calls_write_parquet_to_spec_with_correct_args(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "write_parquet_to_spec") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=_DF_MOCK,
                s3_bucket_spec="my-spec",
                s3_prefix_spec="my-prefix",
                table_name="tb_tmdb_discover_unified_dev",
                database="db_tmdb_unified_dev",
            )

    def test_write_receives_dataframe_returned_by_query(self):
        df_custom = pd.DataFrame([{"id": 99, "media_type": "movie", "year": "2024"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=df_custom),
            patch.object(m, "write_parquet_to_spec") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            actual_df = mock_write.call_args.kwargs["df"]
            pd.testing.assert_frame_equal(actual_df, df_custom)

    def test_pipeline_runs_without_exceptions(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "write_parquet_to_spec"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()

    def test_write_called_exactly_once(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "write_parquet_to_spec") as mock_write,
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            assert mock_write.call_count == 1

    def test_query_called_exactly_once(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK) as mock_query,
            patch.object(m, "write_parquet_to_spec"),
            patch.object(m, "trigger_glue_job"),
        ):
            m.main()
            assert mock_query.call_count == 1

    def test_dataframe_vazio_nao_escreve_mas_aciona_dq(self):
        df_vazio = pd.DataFrame()
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=df_vazio),
            patch.object(m, "write_parquet_to_spec") as mock_write,
            patch.object(m, "trigger_glue_job") as mock_dq,
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
            patch.object(m, "trigger_glue_job", side_effect=lambda *a, **kw: call_order.append("dq")) as mock_dq,
        ):
            m.main()
        mock_dq.assert_called_once_with(
            "dq-job",
            TABLE_NAME="tb_tmdb_discover_unified_dev",
            DATABASE="db_tmdb_unified_dev",
        )
        assert call_order == ["write", "dq"]
