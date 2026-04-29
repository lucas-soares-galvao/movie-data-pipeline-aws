import unittest
from unittest.mock import patch

from app.lambda_api import main


class TestMain(unittest.TestCase):

    @patch("app.lambda_api.main.trigger_glue_etl")
    @patch("app.lambda_api.main.process_configuration")
    @patch("app.lambda_api.main.process_genres")
    @patch("app.lambda_api.main.process_discover")
    @patch("app.lambda_api.main.generate_monthly_periods")
    @patch("app.lambda_api.main.get_tmdb_key")
    @patch("os.getenv")
    def test_lambda_handler_movie(self, mock_getenv, mock_api_key, mock_periods, mock_process_discover, mock_process_genres, mock_process_configuration, mock_glue):
        mock_getenv.side_effect = lambda key: {
            "TMDB_SECRET_ARN": "arn",
            "S3_BUCKET_SOR": "bucket",
            "GLUE_ETL_JOB_NAME": "job"
        }[key]
        mock_api_key.return_value = "fake_key"
        mock_periods.return_value = [
            {"start_date": "2024-01-01", "end_date": "2024-01-31"}
        ]
        mock_process_discover.return_value = ["movie1.json"]
        mock_process_genres.return_value = ["genres_movie.json"]
        mock_process_configuration.return_value = ["configuration_movie.json"]
        mock_glue.return_value = {"job_name": "job", "job_run_id": "123"}

        event = {
            "type": "movie",
            "table_languages": "tb_languages"
        }
        result = main.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["type"], "movie")
        self.assertEqual(result["body"]["discover_files"], ["movie1.json"])
        self.assertEqual(result["body"]["genre_files"], ["genres_movie.json"])
        self.assertEqual(result["body"]["glue"], {"job_name": "job", "job_run_id": "123"})

    @patch("app.lambda_api.main.trigger_glue_etl")
    @patch("app.lambda_api.main.process_configuration")
    @patch("app.lambda_api.main.process_genres")
    @patch("app.lambda_api.main.process_discover")
    @patch("app.lambda_api.main.generate_monthly_periods")
    @patch("app.lambda_api.main.get_tmdb_key")
    @patch("os.getenv")
    def test_lambda_handler_tv(self, mock_getenv, mock_api_key, mock_periods, mock_process_discover, mock_process_genres, mock_process_configuration, mock_glue):
        mock_getenv.side_effect = lambda key: {
            "TMDB_SECRET_ARN": "arn",
            "S3_BUCKET_SOR": "bucket",
            "GLUE_ETL_JOB_NAME": "job"
        }[key]
        mock_api_key.return_value = "fake_key"
        mock_periods.return_value = [
            {"start_date": "2024-01-01", "end_date": "2024-01-31"}
        ]
        mock_process_discover.return_value = ["tv1.json"]
        mock_process_genres.return_value = ["genres_tv.json"]
        mock_process_configuration.return_value = ["configuration_tv.json"]
        mock_glue.return_value = {"job_name": "job", "job_run_id": "123"}

        event = {
            "type": "tv",
            "table_countries": "tb_countries"
        }
        result = main.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["type"], "tv")
        self.assertEqual(result["body"]["discover_files"], ["tv1.json"])
        self.assertEqual(result["body"]["genre_files"], ["genres_tv.json"])
        self.assertEqual(result["body"]["glue"], {"job_name": "job", "job_run_id": "123"})


if __name__ == "__main__":
    unittest.main()