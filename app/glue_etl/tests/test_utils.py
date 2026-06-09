"""Testes unitários para app/glue_etl/src/utils.py."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd

from app.glue_etl.src.utils import (
    SOR_KEYS,
    derive_canonical_name,
    read_from_sor,
    trigger_agg,
    trigger_data_quality,
    trigger_details,
    write_parquet_to_sot,
)


# ---------------------------------------------------------------------------
# derive_canonical_name
# ---------------------------------------------------------------------------

class TestDeriveCanonicalName:
    def test_no_suffix_no_override(self):
        assert derive_canonical_name("Netflix") == "Netflix"

    def test_strips_amazon_channel_suffix(self):
        assert derive_canonical_name("MGM Plus Amazon Channel") == "MGM+"

    def test_strips_premium_suffix(self):
        assert derive_canonical_name("Disney+ Premium") == "Disney+"

    def test_strips_standard_with_ads(self):
        assert derive_canonical_name("Hulu Standard with Ads") == "Hulu"

    def test_strips_with_ads(self):
        assert derive_canonical_name("Peacock with Ads") == "Peacock"

    def test_override_paramount_plus(self):
        assert derive_canonical_name("Paramount Plus") == "Paramount+"

    def test_override_paramount_plus_premium(self):
        # "Paramount Plus Premium" → strip " Plus Premium" → "Paramount" → override
        assert derive_canonical_name("Paramount Plus Premium") == "Paramount+"

    def test_override_mgm_plus(self):
        assert derive_canonical_name("MGM Plus") == "MGM+"

    def test_override_claro_video(self):
        assert derive_canonical_name("Claro video") == "Claro Video"

    def test_strips_only_first_matching_suffix(self):
        # Apenas o primeiro sufixo que casar deve ser removido
        result = derive_canonical_name("Channel Premium")
        assert result == "Channel"

    def test_whitespace_stripped(self):
        assert derive_canonical_name("  Netflix  ") == "Netflix"

    def test_case_insensitive_suffix(self):
        # suffix matching é case-insensitive
        assert derive_canonical_name("Foo PREMIUM") == "Foo"


# ---------------------------------------------------------------------------
# SOR_KEYS structure
# ---------------------------------------------------------------------------

class TestSorKeys:
    def test_movie_and_tv_present(self):
        assert "movie" in SOR_KEYS
        assert "tv" in SOR_KEYS

    def test_all_table_types_present(self):
        for media in ("movie", "tv"):
            for t in ("genre", "configuration", "discover", "watch_providers_ref"):
                assert t in SOR_KEYS[media], f"SOR_KEYS['{media}']['{t}'] ausente"

    def test_discover_key_has_year_placeholder(self):
        assert "{year}" in SOR_KEYS["movie"]["discover"]
        assert "{year}" in SOR_KEYS["tv"]["discover"]


# ---------------------------------------------------------------------------
# read_from_sor
# ---------------------------------------------------------------------------

class TestReadFromSor:
    @patch("app.glue_etl.src.utils.wr")
    def test_discover_calls_read_json_and_adds_year(self, mock_wr):
        mock_wr.s3.read_json.return_value = pd.DataFrame([
            {"id": 1, "title": "Movie A"},
            {"id": 2, "title": "Movie B"},
            {"id": 2, "title": "Movie B dup"},  # duplicata deve ser removida
        ])
        df = read_from_sor("my-sor", "movie", "discover", year="2024")

        mock_wr.s3.read_json.assert_called_once()
        assert "year" in df.columns
        assert (df["year"] == "2024").all()
        assert len(df) == 2  # duplicata removida

    @patch("app.glue_etl.src.utils.boto3")
    def test_genre_reads_via_boto3(self, mock_boto3):
        payload = [{"id": 28, "name": "Action"}, {"id": 12, "name": "Adventure"}]
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: json.dumps(payload).encode())}
        mock_boto3.client.return_value = mock_s3

        df = read_from_sor("my-sor", "movie", "genre")

        assert list(df.columns) == ["id", "name"]
        assert len(df) == 2

    @patch("app.glue_etl.src.utils.boto3")
    def test_configuration_reads_via_boto3(self, mock_boto3):
        payload = [{"iso_639_1": "pt", "english_name": "Portuguese"}]
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: json.dumps(payload).encode())}
        mock_boto3.client.return_value = mock_s3

        df = read_from_sor("my-sor", "movie", "configuration")
        assert len(df) == 1
        assert df.iloc[0]["iso_639_1"] == "pt"

    @patch("app.glue_etl.src.utils.boto3")
    def test_watch_providers_ref_derives_canonical_name(self, mock_boto3):
        payload = [
            {"provider_id": 9, "provider_name": "Amazon Prime Video", "display_priority_br": 1},
            {"provider_id": 119, "provider_name": "Paramount Plus", "display_priority_br": 5},
        ]
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: json.dumps(payload).encode())}
        mock_boto3.client.return_value = mock_s3

        df = read_from_sor("my-sor", "movie", "watch_providers_ref")

        assert "canonical_name" in df.columns
        assert df.loc[df["provider_name"] == "Paramount Plus", "canonical_name"].iloc[0] == "Paramount+"


# ---------------------------------------------------------------------------
# write_parquet_to_sot
# ---------------------------------------------------------------------------

class TestWriteParquetToSot:
    @patch("app.glue_etl.src.utils.wr")
    def test_calls_to_parquet_with_correct_path(self, mock_wr):
        df = pd.DataFrame([{"id": 1}])
        write_parquet_to_sot(df, "my-sot", "tb_genre_movie_tmdb", "db_movie")

        mock_wr.s3.to_parquet.assert_called_once()
        call_kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert call_kwargs["path"] == "s3://my-sot/tmdb/tb_genre_movie_tmdb/"
        assert call_kwargs["database"] == "db_movie"
        assert call_kwargs["table"] == "tb_genre_movie_tmdb"

    @patch("app.glue_etl.src.utils.wr")
    def test_default_mode_is_overwrite_partitions(self, mock_wr):
        df = pd.DataFrame([{"id": 1}])
        write_parquet_to_sot(df, "my-sot", "tb_genre_movie_tmdb", "db_movie")

        call_kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert call_kwargs["mode"] == "overwrite_partitions"

    @patch("app.glue_etl.src.utils.wr")
    def test_partition_cols_passed_through(self, mock_wr):
        df = pd.DataFrame([{"id": 1, "year": "2024"}])
        write_parquet_to_sot(df, "my-sot", "tb_discover_movie_tmdb", "db_movie", partition_cols=["year"])

        call_kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert call_kwargs["partition_cols"] == ["year"]


# ---------------------------------------------------------------------------
# trigger_data_quality
# ---------------------------------------------------------------------------

class TestTriggerDataQuality:
    @patch("app.glue_etl.src.utils.boto3")
    def test_starts_job_without_year(self, mock_boto3):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr-001"}
        mock_boto3.client.return_value = mock_glue

        run_id = trigger_data_quality("dq-job", "tb_genre_movie_tmdb", "db_movie")

        assert run_id == "jr-001"
        args = mock_glue.start_job_run.call_args.kwargs["Arguments"]
        assert "--YEAR" not in args

    @patch("app.glue_etl.src.utils.boto3")
    def test_starts_job_with_year(self, mock_boto3):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr-002"}
        mock_boto3.client.return_value = mock_glue

        run_id = trigger_data_quality("dq-job", "tb_discover_movie_tmdb", "db_movie", year="2024")

        assert run_id == "jr-002"
        args = mock_glue.start_job_run.call_args.kwargs["Arguments"]
        assert args["--YEAR"] == "2024"


# ---------------------------------------------------------------------------
# trigger_agg
# ---------------------------------------------------------------------------

class TestTriggerAgg:
    @patch("app.glue_etl.src.utils.boto3")
    def test_returns_run_id(self, mock_boto3):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr-agg-001"}
        mock_boto3.client.return_value = mock_glue

        run_id = trigger_agg("agg-job")

        assert run_id == "jr-agg-001"
        mock_glue.start_job_run.assert_called_once_with(JobName="agg-job")


# ---------------------------------------------------------------------------
# trigger_details
# ---------------------------------------------------------------------------

class TestTriggerDetails:
    @patch("app.glue_etl.src.utils.boto3")
    def test_passes_correct_arguments(self, mock_boto3):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr-det-001"}
        mock_boto3.client.return_value = mock_glue

        run_id = trigger_details("details-job", "movie", "2024", "2025", "db_movie")

        assert run_id == "jr-det-001"
        args = mock_glue.start_job_run.call_args.kwargs["Arguments"]
        assert args["--MEDIA_TYPE"] == "movie"
        assert args["--YEAR"] == "2024"
        assert args["--END_YEAR"] == "2025"
        assert args["--DATABASE"] == "db_movie"
