# test_translation_called_between_query_and_write verifica a ordem exata
# query → translate → write. Se write ocorrer antes, títulos em inglês são
# salvos na SPEC e o app exibe textos no idioma errado.

from unittest.mock import patch

import pandas as pd

import main as m

_BASE_ARGS = {
    "S3_BUCKET_SPEC": "my-spec",
    "S3_BUCKET_TEMP": "my-temp",
    "DB_MOVIE":   "db_movie_tmdb",
    "DB_TV":      "db_tv_tmdb",
    "DB_UNIFIED": "db_unified_tmdb",
    "TABLE_NAME": "tb_discover_unified_tmdb",
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
            patch.object(m, "traduzir_colunas_en", side_effect=lambda df: df),
            patch.object(m, "write_parquet_to_spec"),
        ):
            m.main()
            mock_query.assert_called_once_with(
                db_movie="db_movie_tmdb",
                db_tv="db_tv_tmdb",
                db_unified="db_unified_tmdb",
                s3_bucket_temp="my-temp",
            )

    def test_calls_write_parquet_to_spec_with_correct_args(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "traduzir_colunas_en", side_effect=lambda df: df),
            patch.object(m, "write_parquet_to_spec") as mock_write,
        ):
            m.main()
            mock_write.assert_called_once_with(
                df=_DF_MOCK,
                s3_bucket_spec="my-spec",
                table_name="tb_discover_unified_tmdb",
                database="db_unified_tmdb",
            )

    def test_write_receives_dataframe_returned_by_query(self):
        df_custom = pd.DataFrame([{"id": 99, "media_type": "movie", "year": "2024"}])
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=df_custom),
            patch.object(m, "traduzir_colunas_en", side_effect=lambda df: df),
            patch.object(m, "write_parquet_to_spec") as mock_write,
        ):
            m.main()
            actual_df = mock_write.call_args.kwargs["df"]
            pd.testing.assert_frame_equal(actual_df, df_custom)

    def test_pipeline_runs_without_exceptions(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "traduzir_colunas_en", side_effect=lambda df: df),
            patch.object(m, "write_parquet_to_spec"),
        ):
            m.main()  # deve concluir sem levantar excecao

    def test_write_called_exactly_once(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "traduzir_colunas_en", side_effect=lambda df: df),
            patch.object(m, "write_parquet_to_spec") as mock_write,
        ):
            m.main()
            assert mock_write.call_count == 1

    def test_query_called_exactly_once(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK) as mock_query,
            patch.object(m, "traduzir_colunas_en", side_effect=lambda df: df),
            patch.object(m, "write_parquet_to_spec"),
        ):
            m.main()
            assert mock_query.call_count == 1

    def test_translation_called_between_query_and_write(self):
        call_order = []
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(
                m,
                "run_athena_query",
                side_effect=lambda **_: call_order.append("query") or _DF_MOCK,
            ),
            patch.object(
                m,
                "traduzir_colunas_en",
                side_effect=lambda df: call_order.append("translate") or df,
            ),
            patch.object(
                m,
                "write_parquet_to_spec",
                side_effect=lambda **_: call_order.append("write"),
            ),
        ):
            m.main()
            assert call_order == ["query", "translate", "write"]

    def test_translation_called_exactly_once(self):
        with (
            patch.object(m, "get_parameters_glue", return_value=_BASE_ARGS),
            patch.object(m, "run_athena_query", return_value=_DF_MOCK),
            patch.object(m, "traduzir_colunas_en", side_effect=lambda df: df) as mock_translate,
            patch.object(m, "write_parquet_to_spec"),
        ):
            m.main()
            assert mock_translate.call_count == 1
