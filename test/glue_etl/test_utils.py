"""Testes unitários para app/glue_etl/src/utils.py."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd

from src.utils import derive_canonical_name, read_from_sor, trigger_agg, trigger_data_quality, trigger_details, write_parquet_to_sot


# ---------------------------------------------------------------------------
# Helpers compartilhados
# ---------------------------------------------------------------------------


def _make_s3_mock(payload) -> MagicMock:
    """Cria um cliente S3 simulado que retorna `payload` serializado como JSON."""
    body = MagicMock()
    body.read.return_value = json.dumps(payload).encode()
    s3_mock = MagicMock()
    s3_mock.get_object.return_value = {"Body": body}
    return s3_mock


# ---------------------------------------------------------------------------
# read_from_sor — table_type="discover"
# ---------------------------------------------------------------------------


class TestReadFromSorDiscover:
    def test_calls_wrangler_with_correct_path(self):
        df_mock = pd.DataFrame(
            [{"id": 1, "title": "Film A"}, {"id": 2, "title": "Film B"}]
        )
        with patch("awswrangler.s3.read_json", return_value=df_mock) as mock_read:
            read_from_sor("my-sor", "movie", "discover", year="2023")
            mock_read.assert_called_once_with(
                path="s3://my-sor/tmdb/discover/movie/ano=2023/",
                orient="records",
            )

    def test_adds_year_column(self):
        df_mock = pd.DataFrame([{"id": 1, "title": "Film A"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2023")
            assert "year" in result.columns
            assert result["year"].iloc[0] == "2023"

    def test_year_column_value_matches_arg(self):
        df_mock = pd.DataFrame([{"id": 1}, {"id": 2}])
        with patch("awswrangler.s3.read_json", return_value=df_mock):
            result = read_from_sor("my-sor", "movie", "discover", year="2000")
            assert (result["year"] == "2000").all()

    def test_tv_uses_correct_path(self):
        df_mock = pd.DataFrame([{"id": 10, "name": "Serie A"}])
        with patch("awswrangler.s3.read_json", return_value=df_mock) as mock_read:
            read_from_sor("my-sor", "tv", "discover", year="2022")
            mock_read.assert_called_once_with(
                path="s3://my-sor/tmdb/discover/tv/ano=2022/",
                orient="records",
            )


# ---------------------------------------------------------------------------
# read_from_sor — table_type="genre"
# ---------------------------------------------------------------------------


class TestReadFromSorGenre:
    def test_movie_reads_correct_s3_key(self):
        s3_mock = _make_s3_mock([{"id": 28, "name": "Ação"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "movie", "genre")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/genre/movie/generos_filmes.json",
            )

    def test_tv_reads_correct_s3_key(self):
        s3_mock = _make_s3_mock([{"id": 10759, "name": "Ação & Aventura"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "tv", "genre")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/genre/tv/generos_series.json",
            )

    def test_returns_dataframe_from_list(self):
        genres = [{"id": 28, "name": "Ação"}, {"id": 12, "name": "Aventura"}]
        s3_mock = _make_s3_mock(genres)
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "genre")
            assert len(result) == 2
            assert list(result.columns) == ["id", "name"]
            assert result["id"].tolist() == [28, 12]


# ---------------------------------------------------------------------------
# read_from_sor — table_type="watch_providers_ref"
# ---------------------------------------------------------------------------


class TestReadFromSorWatchProvidersRef:
    def _make_s3_mock(self, payload) -> MagicMock:
        body = MagicMock()
        body.read.return_value = json.dumps(payload).encode()
        s3_mock = MagicMock()
        s3_mock.get_object.return_value = {"Body": body}
        return s3_mock

    def test_movie_reads_correct_s3_key(self):
        providers = [{"provider_id": 8, "provider_name": "Netflix", "logo_path": "/n.png", "display_priority_br": 1}]
        s3_mock = self._make_s3_mock(providers)
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "movie", "watch_providers_ref")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/watch_providers_ref/movie/watch_providers_ref.json",
            )

    def test_tv_reads_correct_s3_key(self):
        providers = [{"provider_id": 9, "provider_name": "Prime Video", "logo_path": "/p.png", "display_priority_br": 2}]
        s3_mock = self._make_s3_mock(providers)
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "tv", "watch_providers_ref")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/watch_providers_ref/tv/watch_providers_ref.json",
            )

    def test_adds_canonical_name_column(self):
        providers = [{"provider_id": 8, "provider_name": "Netflix Standard with Ads", "logo_path": None, "display_priority_br": None}]
        s3_mock = self._make_s3_mock(providers)
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "watch_providers_ref")
            assert "canonical_name" in result.columns
            assert result["canonical_name"].iloc[0] == "Netflix"

    def test_canonical_name_override_applied(self):
        providers = [{"provider_id": 99, "provider_name": "Paramount Plus", "logo_path": None, "display_priority_br": None}]
        s3_mock = self._make_s3_mock(providers)
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "watch_providers_ref")
            assert result["canonical_name"].iloc[0] == "Paramount+"


# ---------------------------------------------------------------------------
# read_from_sor — table_type="configuration"
# ---------------------------------------------------------------------------


class TestReadFromSorConfiguration:
    def test_movie_reads_languages_s3_key(self):
        s3_mock = _make_s3_mock([{"iso_639_1": "pt", "english_name": "Portuguese"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "movie", "configuration")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/configuration/languages/idiomas.json",
            )

    def test_tv_reads_countries_s3_key(self):
        s3_mock = _make_s3_mock([{"iso_3166_1": "BR", "english_name": "Brazil"}])
        with patch("boto3.client", return_value=s3_mock):
            read_from_sor("my-sor", "tv", "configuration")
            s3_mock.get_object.assert_called_once_with(
                Bucket="my-sor",
                Key="tmdb/configuration/countries/paises.json",
            )

    def test_returns_dataframe_from_list(self):
        s3_mock = _make_s3_mock([{"iso_639_1": "pt"}, {"iso_639_1": "en"}])
        with patch("boto3.client", return_value=s3_mock):
            result = read_from_sor("my-sor", "movie", "configuration")
            assert len(result) == 2
            assert "iso_639_1" in result.columns


# ---------------------------------------------------------------------------
# write_parquet_to_sot
# ---------------------------------------------------------------------------


class TestWriteParquetToSot:
    def test_with_partition_cols(self):
        df = pd.DataFrame([{"id": 1, "year": "2023"}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_discover_movie_tmdb",
                database="db_tmdb",
                partition_cols=["year"],
            )
            mock_write.assert_called_once_with(
                df=df,
                path="s3://my-sot/tmdb/tb_discover_movie_tmdb/",
                dataset=True,
                partition_cols=["year"],
                mode="overwrite_partitions",
                database="db_tmdb",
                table="tb_discover_movie_tmdb",
            )

    def test_without_partition_cols_defaults_to_none(self):
        df = pd.DataFrame([{"id": 28, "name": "Ação"}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_genre_movie_tmdb",
                database="db_tmdb",
            )
            mock_write.assert_called_once_with(
                df=df,
                path="s3://my-sot/tmdb/tb_genre_movie_tmdb/",
                dataset=True,
                partition_cols=None,
                mode="overwrite_partitions",
                database="db_tmdb",
                table="tb_genre_movie_tmdb",
            )

    def test_custom_mode_is_forwarded(self):
        df = pd.DataFrame([{"id": 1}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="my-sot",
                table_name="tb_test",
                database="db_tmdb",
                mode="overwrite",
            )
            _, kwargs = mock_write.call_args
            assert kwargs["mode"] == "overwrite"

    def test_s3_path_uses_table_name(self):
        df = pd.DataFrame([{"id": 1}])
        with patch("awswrangler.s3.to_parquet") as mock_write:
            write_parquet_to_sot(
                df=df,
                s3_bucket_sot="bucket-sot",
                table_name="tb_custom",
                database="db_tmdb",
            )
            _, kwargs = mock_write.call_args
            assert kwargs["path"] == "s3://bucket-sot/tmdb/tb_custom/"


# ---------------------------------------------------------------------------
# derive_canonical_name
# ---------------------------------------------------------------------------


class TestDeriveCanonicalName:
    def test_remove_sufixo_standard_with_ads(self):
        assert derive_canonical_name("Netflix Standard with Ads") == "Netflix"

    def test_remove_sufixo_with_ads(self):
        assert derive_canonical_name("Max with Ads") == "Max"

    def test_remove_sufixo_plus_premium(self):
        # " Plus Premium" é sufixo próprio na lista — remove tudo junto
        assert derive_canonical_name("Disney Plus Premium") == "Disney"

    def test_remove_sufixo_premium_simples(self):
        assert derive_canonical_name("HBO Premium") == "HBO"

    def test_remove_sufixo_amazon_channel(self):
        assert derive_canonical_name("Telecine Amazon Channel") == "Telecine"

    def test_override_paramount_plus(self):
        assert derive_canonical_name("Paramount Plus") == "Paramount+"

    def test_override_claro_video(self):
        assert derive_canonical_name("Claro video") == "Claro Video"

    def test_nome_sem_sufixo_permanece_inalterado(self):
        assert derive_canonical_name("Netflix") == "Netflix"

    def test_plus_premium_tem_prioridade_sobre_premium(self):
        # " Plus Premium" aparece antes de " Premium" na lista, então é removido primeiro
        assert derive_canonical_name("Canal Plus Premium") == "Canal"


# ---------------------------------------------------------------------------
# trigger_agg
# ---------------------------------------------------------------------------


class TestTriggerAgg:
    def _make_glue_mock(self, run_id="run-agg-123") -> MagicMock:
        glue_mock = MagicMock()
        glue_mock.start_job_run.return_value = {"JobRunId": run_id}
        return glue_mock

    def test_calls_start_job_run_with_job_name(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_agg("agg-job")
            glue_mock.start_job_run.assert_called_once_with(JobName="agg-job")

    def test_returns_job_run_id(self):
        glue_mock = self._make_glue_mock(run_id="run-agg-xyz")
        with patch("boto3.client", return_value=glue_mock):
            run_id = trigger_agg("agg-job")
            assert run_id == "run-agg-xyz"


# ---------------------------------------------------------------------------
# trigger_data_quality
# ---------------------------------------------------------------------------


class TestTriggerDataQuality:
    def _make_glue_mock(self, run_id="run-123") -> MagicMock:
        glue_mock = MagicMock()
        glue_mock.start_job_run.return_value = {"JobRunId": run_id}
        return glue_mock

    def test_calls_start_job_run_with_correct_args(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_data_quality("dq-job", "tb_genre_movie_tmdb", "db_tmdb")
            glue_mock.start_job_run.assert_called_once_with(
                JobName="dq-job",
                Arguments={
                    "--TABLE_NAME": "tb_genre_movie_tmdb",
                    "--DATABASE": "db_tmdb",
                },
            )

    def test_includes_year_when_provided(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_data_quality(
                "dq-job", "tb_discover_movie_tmdb", "db_tmdb", year="2023"
            )
            _, kwargs = glue_mock.start_job_run.call_args
            assert kwargs["Arguments"]["--YEAR"] == "2023"

    def test_omits_year_when_not_provided(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_data_quality("dq-job", "tb_genre_movie_tmdb", "db_tmdb")
            _, kwargs = glue_mock.start_job_run.call_args
            assert "--YEAR" not in kwargs["Arguments"]

    def test_returns_job_run_id(self):
        glue_mock = self._make_glue_mock(run_id="run-abc")
        with patch("boto3.client", return_value=glue_mock):
            run_id = trigger_data_quality("dq-job", "tb_genre_movie_tmdb", "db_tmdb")
            assert run_id == "run-abc"


# ---------------------------------------------------------------------------
# trigger_details
# ---------------------------------------------------------------------------


class TestTriggerDetails:
    def _make_glue_mock(self, run_id="run-det-123") -> MagicMock:
        glue_mock = MagicMock()
        glue_mock.start_job_run.return_value = {"JobRunId": run_id}
        return glue_mock

    def test_passes_all_required_arguments(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_details(
                "details-job",
                media_type="movie",
                year="2025",
                end_year="2026",
                database="db_movie_tmdb",
            )
            glue_mock.start_job_run.assert_called_once_with(
                JobName="details-job",
                Arguments={
                    "--MEDIA_TYPE": "movie",
                    "--YEAR":       "2025",
                    "--END_YEAR":   "2026",
                    "--DATABASE":   "db_movie_tmdb",
                },
            )

    def test_database_forwarded_for_movie(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_details(
                "details-job",
                media_type="movie",
                year="2025",
                end_year="2026",
                database="db_movie_tmdb",
            )
            _, kwargs = glue_mock.start_job_run.call_args
            assert kwargs["Arguments"]["--DATABASE"] == "db_movie_tmdb"

    def test_database_forwarded_for_tv(self):
        glue_mock = self._make_glue_mock()
        with patch("boto3.client", return_value=glue_mock):
            trigger_details(
                "details-job",
                media_type="tv",
                year="2024",
                end_year="2025",
                database="db_tv_tmdb",
            )
            _, kwargs = glue_mock.start_job_run.call_args
            assert kwargs["Arguments"]["--DATABASE"] == "db_tv_tmdb"
            assert kwargs["Arguments"]["--MEDIA_TYPE"] == "tv"

    def test_returns_job_run_id(self):
        glue_mock = self._make_glue_mock(run_id="run-det-xyz")
        with patch("boto3.client", return_value=glue_mock):
            run_id = trigger_details(
                "details-job",
                media_type="tv",
                year="2025",
                end_year="2025",
                database="db_tv_tmdb",
            )
            assert run_id == "run-det-xyz"
