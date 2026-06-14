import pytest
from unittest.mock import patch, MagicMock

import pandas as pd

from src.utils import get_parameters_glue, get_resolved_option, run_athena_query, trigger_data_quality, write_parquet_to_spec


class TestRunAthenaQuery:
    def test_passes_sql_with_image_columns_to_wrangler(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")

            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "AS poster_url" in sql
            assert "AS backdrop_url" in sql
            assert "https://image.tmdb.org/t/p/w342" in sql
            assert "https://image.tmdb.org/t/p/w780" in sql
            assert "tb_discover_movie_tmdb" in sql
            assert "tb_discover_tv_tmdb" in sql
            assert "overview" in sql
            assert "air_date" in sql
            assert "origin_country_name" in sql
            assert "language_name" in sql

    def test_uses_expected_wrangler_execution_args(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")

            mock_read.assert_called_once()
            _, kwargs = mock_read.call_args
            assert kwargs["database"] == "db_unified_tmdb"
            assert kwargs["s3_output"] == "s3://my-temp/athena/glue_agg/"
            assert kwargs["ctas_approach"] is True

    def test_query_contains_details_movie_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_details_movie_tmdb" in sql
            assert "runtime_minutes" in sql

    def test_query_contains_details_tv_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_details_tv_tmdb" in sql
            assert "number_of_seasons" in sql
            assert "number_of_episodes" in sql
            assert "episode_runtime_minutes" in sql

    def test_query_contains_watch_providers_join(self):
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

            assert "tb_watch_providers_movie_tmdb" in sql
            assert "tb_watch_providers_tv_tmdb" in sql
            assert "streaming_providers" in sql

    def test_query_deduplica_watch_providers_por_ano_mais_recente(self):
        """movie_wp_recent e tv_wp_recent devem usar DENSE_RANK por year DESC.
        DENSE_RANK (não ROW_NUMBER) garante que TODOS os provedores do ano mais recente
        recebam rank=1, evitando filtrar apenas um provedor por título."""
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

        assert "movie_wp_recent" in sql
        assert "tv_wp_recent" in sql
        assert "CAST(year AS INTEGER) DESC" in sql
        assert "DENSE_RANK()" in sql
        assert "ROW_NUMBER() OVER (PARTITION BY id ORDER BY CAST(year AS INTEGER) DESC)" not in sql

    def test_query_possui_dedup_final_spec_deduped(self):
        """spec_raw e spec_deduped garantem unicidade por (id, media_type) na saída."""
        with patch("awswrangler.athena.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            run_athena_query(db_movie="db_movie_tmdb", db_tv="db_tv_tmdb", db_unified="db_unified_tmdb", s3_bucket_temp="my-temp")
            _, kwargs = mock_read.call_args
            sql = kwargs["sql"]

        assert "spec_raw" in sql
        assert "spec_deduped" in sql
        assert "PARTITION BY id, media_type" in sql
        assert "rn_final" in sql



class TestWriteParquetToSpec:
    def test_constroi_caminho_s3_correto(self):
        df = pd.DataFrame({"col": [1]})
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_spec(df, s3_bucket_spec="my-spec", table_name="tb_unified", database="db_spec")

            _, kwargs = mock_write.call_args
            assert kwargs["path"] == "s3://my-spec/tb_unified/"

    def test_usa_partition_cols_e_mode_corretos(self):
        df = pd.DataFrame({"col": [1]})
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_spec(df, s3_bucket_spec="my-spec", table_name="tb_unified", database="db_spec")

            _, kwargs = mock_write.call_args
            assert kwargs["partition_cols"] == ["media_type", "year"]
            assert kwargs["mode"] == "overwrite"
            assert kwargs["dataset"] is True

    def test_dataframe_vazio_nao_escreve(self):
        df = pd.DataFrame()
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_spec(df, s3_bucket_spec="my-spec", table_name="tb_unified", database="db_spec")

            mock_write.assert_not_called()

    def test_registra_tabela_no_catalog(self):
        df = pd.DataFrame({"col": [1]})
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_spec(df, s3_bucket_spec="my-spec", table_name="tb_unified", database="db_spec")

            _, kwargs = mock_write.call_args
            assert kwargs["database"] == "db_spec"
            assert kwargs["table"] == "tb_unified"

    def test_levanta_runtime_error_quando_nenhum_arquivo_escrito(self):
        df = pd.DataFrame({"col": [1]})
        with patch("awswrangler.s3.to_parquet", return_value={"paths": []}):
            with pytest.raises(RuntimeError, match="Escrita falhou"):
                write_parquet_to_spec(df, s3_bucket_spec="my-spec", table_name="tb_unified", database="db_spec")


class TestGetResolvedOption:
    def test_delegates_to_getResolvedOptions(self):
        with patch("src.utils.getResolvedOptions", return_value={"TABLE_NAME": "tb_unified"}) as mock_gro:
            result = get_resolved_option(["TABLE_NAME"])
        mock_gro.assert_called_once()
        assert result == {"TABLE_NAME": "tb_unified"}


class TestGetParametersGlue:
    def _required(self):
        return {
            "S3_BUCKET_SPEC": "spec",
            "S3_BUCKET_TEMP": "tmp",
            "DB_MOVIE": "db_movie",
            "DB_TV": "db_tv",
            "DB_UNIFIED": "db_unified",
            "TABLE_NAME": "tb_unified",
            "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
        }

    def test_returns_all_required_args(self):
        with patch("src.utils.get_resolved_option", return_value=self._required()):
            result = get_parameters_glue()
        assert result["S3_BUCKET_SPEC"] == "spec"
        assert result["DB_UNIFIED"] == "db_unified"
        assert result["TABLE_NAME"] == "tb_unified"
        assert result["GLUE_DATA_QUALITY_JOB_NAME"] == "dq-job"


class TestTriggerDataQuality:
    def test_inicia_job_sem_year(self):
        mock_client = MagicMock()
        mock_client.start_job_run.return_value = {"JobRunId": "run-abc"}
        mock_client.get_job_run.return_value = {"JobRun": {"JobRunState": "SUCCEEDED"}}
        with patch("src.utils.boto3.client", return_value=mock_client):
            with patch("src.utils.time.sleep"):
                run_id = trigger_data_quality(
                    dq_job_name="dq-job",
                    table_name="tb_content",
                    database="db_unified",
                )
        assert run_id == "run-abc"
        call_args = mock_client.start_job_run.call_args
        arguments = call_args.kwargs["Arguments"]
        assert arguments["--TABLE_NAME"] == "tb_content"
        assert arguments["--DATABASE"] == "db_unified"
        assert "--YEAR" not in arguments

    def test_inicia_job_com_year(self):
        mock_client = MagicMock()
        mock_client.start_job_run.return_value = {"JobRunId": "run-xyz"}
        mock_client.get_job_run.return_value = {"JobRun": {"JobRunState": "SUCCEEDED"}}
        with patch("src.utils.boto3.client", return_value=mock_client):
            with patch("src.utils.time.sleep"):
                run_id = trigger_data_quality(
                    dq_job_name="dq-job",
                    table_name="tb_content",
                    database="db_unified",
                    year="2025",
                )
        assert run_id == "run-xyz"
        arguments = mock_client.start_job_run.call_args.kwargs["Arguments"]
        assert arguments["--YEAR"] == "2025"

    def test_aguarda_conclusao_apos_estado_succeeded(self):
        mock_client = MagicMock()
        mock_client.start_job_run.return_value = {"JobRunId": "run-abc"}
        mock_client.get_job_run.side_effect = [
            {"JobRun": {"JobRunState": "RUNNING"}},
            {"JobRun": {"JobRunState": "SUCCEEDED"}},
        ]
        with patch("src.utils.boto3.client", return_value=mock_client):
            with patch("src.utils.time.sleep") as mock_sleep:
                trigger_data_quality(dq_job_name="dq-job", table_name="tb", database="db")
        assert mock_client.get_job_run.call_count == 2
        assert mock_sleep.call_count == 1

    def test_aguarda_multiplas_iteracoes_ate_estado_terminal(self):
        mock_client = MagicMock()
        mock_client.start_job_run.return_value = {"JobRunId": "run-xyz"}
        mock_client.get_job_run.side_effect = [
            {"JobRun": {"JobRunState": "RUNNING"}},
            {"JobRun": {"JobRunState": "RUNNING"}},
            {"JobRun": {"JobRunState": "FAILED"}},
        ]
        with patch("src.utils.boto3.client", return_value=mock_client):
            with patch("src.utils.time.sleep"):
                trigger_data_quality(dq_job_name="dq-job", table_name="tb", database="db")
        assert mock_client.get_job_run.call_count == 3
