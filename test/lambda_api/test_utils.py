"""Raciocinio: valida integracoes utilitarias (Secrets, periodos, requests e serializacao)."""

import unittest
from unittest.mock import patch, MagicMock

from app.lambda_api.src import utils


class TestUtils(unittest.TestCase):

    @patch("boto3.client")
    def test_get_tmdb_key(self, mock_boto):
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"tmdb_api_key": "123"}'
        }
        mock_boto.return_value = mock_client

        result = utils.get_tmdb_key("fake_arn")

        self.assertEqual(result, "123")

    def test_generate_monthly_periods(self):
        periods = utils.generate_monthly_periods(start_year=2024)

        self.assertTrue(len(periods) > 0)
        self.assertIn("start_date", periods[0])
        self.assertIn("end_date", periods[0])

    @patch("requests.get")
    def test_fetch_discover_movie(self, mock_get):
        # Simulates empty response for pt-BR and response with movie for en-US
        mock_response_pt = MagicMock()
        mock_response_pt.json.return_value = {
            "results": [],
            "total_pages": 1
        }
        mock_response_pt.raise_for_status.return_value = None

        mock_response_en = MagicMock()
        mock_response_en.json.return_value = {
            "results": [{"id": 1}, {"id": 2}],
            "total_pages": 1
        }
        mock_response_en.raise_for_status.return_value = None

        mock_get.side_effect = [mock_response_pt, mock_response_en]

        period = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31"
        }

        movie = utils.fetch_discover("fake_key", period, media_type="movie")

        self.assertEqual(len(movie), 2)
        self.assertEqual(movie[0]["id"], 1)
        self.assertEqual(movie[1]["id"], 2)

    @patch("requests.get")
    def test_fetch_discover_tv(self, mock_get):
        # Simulates empty response for pt-BR and response with tv for en-US
        mock_response_pt = MagicMock()
        mock_response_pt.json.return_value = {
            "results": [],
            "total_pages": 1
        }
        mock_response_pt.raise_for_status.return_value = None

        mock_response_en = MagicMock()
        mock_response_en.json.return_value = {
            "results": [{"id": 10}, {"id": 20}],
            "total_pages": 1
        }
        mock_response_en.raise_for_status.return_value = None

        mock_get.side_effect = [mock_response_pt, mock_response_en]

        period = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31"
        }

        tv = utils.fetch_discover("fake_key", period, media_type="tv")

        self.assertEqual(len(tv), 2)
        self.assertEqual(tv[0]["id"], 10)
        self.assertEqual(tv[1]["id"], 20)

    @patch("requests.get")
    def test_fetch_genres_movie(self, mock_get):
        # Simulates empty response for pt-BR and response with genres for en-US
        mock_response_pt = MagicMock()
        mock_response_pt.json.return_value = {"genres": []}
        mock_response_pt.raise_for_status.return_value = None

        mock_response_en = MagicMock()
        mock_response_en.json.return_value = {"genres": [{"id": 1, "name": "Action"}]}
        mock_response_en.raise_for_status.return_value = None

        mock_get.side_effect = [mock_response_pt, mock_response_en]

        genres = utils.fetch_genres("fake_key", media_type="movie")
        self.assertEqual(len(genres), 1)
        self.assertEqual(genres[0]["id"], 1)
        self.assertEqual(genres[0]["name"], "Action")

    @patch("requests.get")
    def test_fetch_genres_tv(self, mock_get):
        # Simulates empty response for pt-BR and response with genres for en-US
        mock_response_pt = MagicMock()
        mock_response_pt.json.return_value = {"genres": []}
        mock_response_pt.raise_for_status.return_value = None

        mock_response_en = MagicMock()
        mock_response_en.json.return_value = {"genres": [{"id": 2, "name": "Drama"}]}
        mock_response_en.raise_for_status.return_value = None

        mock_get.side_effect = [mock_response_pt, mock_response_en]

        genres = utils.fetch_genres("fake_key", media_type="tv")
        self.assertEqual(len(genres), 1)
        self.assertEqual(genres[0]["id"], 2)
        self.assertEqual(genres[0]["name"], "Drama")

    @patch("boto3.client")
    def test_save_json_to_s3(self, mock_boto):
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        utils.save_json_to_s3("bucket", "key.json", {"a": 1})

        mock_s3.put_object.assert_called_once()


    @patch("boto3.client")
    def test_trigger_glue_etl(self, mock_boto):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {
            "JobRunId": "abc123"
        }
        mock_boto.return_value = mock_glue

        params = {
            "media_type": "movie",
            "database": "db_tmdb",
            "discover_table": "tb_discover_movie_tmdb",
            "genre_table": "tb_genre_movie_tmdb",
            "configuration_table": "tb_configuration_movie_tmdb",
            "configuration": "languages",
            "partition_columns": "year,month"
        }
        result = utils.trigger_glue_etl("job_test", params, year="2024", table_scope="discover")

        self.assertEqual(result["job_name"], "job_test")
        self.assertEqual(result["job_run_id"], "abc123")
        call_args = mock_glue.start_job_run.call_args
        self.assertEqual(call_args.kwargs["Arguments"]["--YEAR"], "2024")
        self.assertEqual(call_args.kwargs["Arguments"]["--TABLE_SCOPE"], "discover")

    def test_group_periods_by_year(self):
        periods = [
            {"start_date": "2023-11-01", "end_date": "2023-11-30"},
            {"start_date": "2023-12-01", "end_date": "2023-12-31"},
            {"start_date": "2024-01-01", "end_date": "2024-01-31"},
        ]
        result = utils.group_periods_by_year(periods)

        self.assertIn("2023", result)
        self.assertIn("2024", result)
        self.assertEqual(len(result["2023"]), 2)
        self.assertEqual(len(result["2024"]), 1)

    def test_extract_media_tables(self):
        event = {
            "type": "movie",
            "table_discover_movie": "tb_discover_movie_tmdb",  # CORRETO!
            "table_genre_movie": "tb_genre_movie_tmdb",
            "table_configuration_languages": "tb_languages"
        }
        result = utils.extract_media_tables(event)
        self.assertEqual(result["discover_table"], "tb_discover_movie_tmdb")

    def test_extract_media_tables_invalid_type(self):
        event = {
            "type": "anime"
        }
        with self.assertRaises(ValueError):
            utils.extract_media_tables(event)

    def test_process_configuration_empty_type(self):
        result = utils.process_configuration("fake_key", "bucket", "")
        self.assertEqual(result, [])

    def test_fetch_configuration_invalid_type(self):
        with self.assertRaises(ValueError):
            utils.fetch_configuration("fake_key", configuration_type="invalid")

    @patch("requests.get")
    def test_fetch_configuration_languages(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"iso_639_1": "pt", "english_name": "Portuguese"}]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = utils.fetch_configuration("fake_key", configuration_type="languages")

        self.assertEqual(result, [{"iso_639_1": "pt", "english_name": "Portuguese"}])
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["language"], "pt-BR")

    @patch("requests.get")
    def test_fetch_configuration_countries(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"iso_3166_1": "BR", "english_name": "Brazil"}]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = utils.fetch_configuration("fake_key", configuration_type="countries")

        self.assertEqual(result, [{"iso_3166_1": "BR", "english_name": "Brazil"}])
        params = mock_get.call_args.kwargs["params"]
        self.assertNotIn("language", params)


if __name__ == "__main__":
    unittest.main()
