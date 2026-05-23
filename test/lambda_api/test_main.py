"""Raciocinio: valida o fluxo do handler por tipo de midia e as condicoes de disparo do Glue."""

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
            "table_discover_movie": "tb_discover_movie_tmdb",
            "table_genre_movie": "tb_genre_movie_tmdb",
            "table_configuration_languages": "tb_languages"
        }
        result = main.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["type"], "movie")
        self.assertEqual(result["body"]["discover_files"], ["movie1.json"])
        self.assertEqual(result["body"]["genre_files"], ["genres_movie.json"])
        self.assertEqual(
            result["body"]["glue"],
            [
                {"job_name": "job", "job_run_id": "123"},
                {"job_name": "job", "job_run_id": "123"}
            ]
        )
        self.assertEqual(mock_glue.call_count, 2)
        self.assertEqual(
            mock_glue.call_args_list[0].kwargs,
            {"table_scope": "static"}
        )
        self.assertEqual(
            mock_glue.call_args_list[1].kwargs,
            {"year": "2024", "table_scope": "discover"}
        )

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
            "table_discover_tv": "tb_discover_tv_tmdb",
            "table_genre_tv": "tb_genre_tv_tmdb",
            "table_configuration_countries": "tb_countries"
        }
        result = main.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["type"], "tv")
        self.assertEqual(result["body"]["discover_files"], ["tv1.json"])
        self.assertEqual(result["body"]["genre_files"], ["genres_tv.json"])
        self.assertEqual(
            result["body"]["glue"],
            [
                {"job_name": "job", "job_run_id": "123"},
                {"job_name": "job", "job_run_id": "123"}
            ]
        )
        self.assertEqual(mock_glue.call_count, 2)
        self.assertEqual(
            mock_glue.call_args_list[0].kwargs,
            {"table_scope": "static"}
        )
        self.assertEqual(
            mock_glue.call_args_list[1].kwargs,
            {"year": "2024", "table_scope": "discover"}
        )

    @patch("app.lambda_api.main.trigger_glue_etl")
    @patch("app.lambda_api.main.process_configuration")
    @patch("app.lambda_api.main.process_genres")
    @patch("app.lambda_api.main.process_discover")
    @patch("app.lambda_api.main.generate_monthly_periods")
    @patch("app.lambda_api.main.get_tmdb_key")
    @patch("os.getenv")
    def test_lambda_handler_no_discover_files_skips_glue(self, mock_getenv, mock_api_key, mock_periods, mock_process_discover, mock_process_genres, mock_process_configuration, mock_glue):
        mock_getenv.side_effect = lambda key: {
            "TMDB_SECRET_ARN": "arn",
            "S3_BUCKET_SOR": "bucket",
            "GLUE_ETL_JOB_NAME": "job"
        }[key]
        mock_api_key.return_value = "fake_key"
        mock_periods.return_value = [
            {"start_date": "2024-01-01", "end_date": "2024-01-31"}
        ]
        mock_process_discover.return_value = []
        mock_process_genres.return_value = ["genres_movie.json"]
        mock_process_configuration.return_value = ["configuration_movie.json"]
        mock_glue.return_value = {"job_name": "job", "job_run_id": "123"}

        event = {
            "type": "movie",
            "table_discover_movie": "tb_discover_movie_tmdb",
            "table_genre_movie": "tb_genre_movie_tmdb",
            "table_configuration_languages": "tb_languages"
        }
        result = main.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"]["glue"], [{"job_name": "job", "job_run_id": "123"}])
        mock_glue.assert_called_once_with("job", mock_glue.call_args[0][1], table_scope="static")

    @patch("os.getenv")
    def test_lambda_handler_invalid_media_type(self, mock_getenv):
        mock_getenv.side_effect = lambda key: {
            "TMDB_SECRET_ARN": "arn",
            "S3_BUCKET_SOR": "bucket",
            "GLUE_ETL_JOB_NAME": "job"
        }[key]

        event = {
            "type": "anime"
        }
        result = main.lambda_handler(event, None)

        self.assertEqual(result["statusCode"], 400)
        self.assertIn("Unsupported media type", result["body"]["error"])


if __name__ == "__main__":
    unittest.main()
