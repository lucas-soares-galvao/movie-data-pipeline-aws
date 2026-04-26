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
        # Simulates empty response for pt-BR and response with movies for en-US
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

        movies = utils.fetch_discover("fake_key", period, media_type="movie")

        self.assertEqual(len(movies), 2)
        self.assertEqual(movies[0]["id"], 1)
        self.assertEqual(movies[1]["id"], 2)

    @patch("requests.get")
    def test_fetch_discover_tv(self, mock_get):
        # Simulates empty response for pt-BR and response with series for en-US
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

        series = utils.fetch_discover("fake_key", period, media_type="tv")

        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["id"], 10)
        self.assertEqual(series[1]["id"], 20)

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

        result = utils.trigger_glue_etl("job_test")

        self.assertEqual(result["job_name"], "job_test")
        self.assertEqual(result["job_run_id"], "abc123")


if __name__ == "__main__":
    unittest.main()