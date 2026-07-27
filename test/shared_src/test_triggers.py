from unittest.mock import MagicMock, patch

from shared_utils.triggers import trigger_glue_job


class TestTriggerGlueJob:
    def _make_glue_mock(self, run_id="run-123"):
        glue_mock = MagicMock()
        glue_mock.start_job_run.return_value = {"JobRunId": run_id}
        return glue_mock

    def test_calls_start_job_run_with_job_name(self):
        glue_mock = self._make_glue_mock()
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock):
            trigger_glue_job("my-job")
            glue_mock.start_job_run.assert_called_once_with(
                JobName="my-job", Arguments={}
            )

    def test_converts_kwargs_to_glue_arguments(self):
        glue_mock = self._make_glue_mock()
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock):
            trigger_glue_job("dq-job", TABLE_NAME="tb_x", DATABASE="db_y")
            glue_mock.start_job_run.assert_called_once_with(
                JobName="dq-job",
                Arguments={"--TABLE_NAME": "tb_x", "--DATABASE": "db_y"},
            )

    def test_omits_none_values(self):
        glue_mock = self._make_glue_mock()
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock):
            trigger_glue_job("dq-job", TABLE_NAME="tb_x", DATABASE="db_y", YEAR=None)
            args = glue_mock.start_job_run.call_args.kwargs["Arguments"]
            assert "--YEAR" not in args

    def test_includes_year_when_provided(self):
        glue_mock = self._make_glue_mock()
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock):
            trigger_glue_job("dq-job", TABLE_NAME="tb_x", DATABASE="db_y", YEAR="2025")
            args = glue_mock.start_job_run.call_args.kwargs["Arguments"]
            assert args["--YEAR"] == "2025"

    def test_returns_job_run_id(self):
        glue_mock = self._make_glue_mock(run_id="run-abc-xyz")
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock):
            run_id = trigger_glue_job("my-job")
            assert run_id == "run-abc-xyz"

    def test_passes_all_details_arguments(self):
        glue_mock = self._make_glue_mock()
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock):
            trigger_glue_job(
                "details-job",
                MEDIA_TYPE="movie",
                YEAR="2025",
                END_YEAR="2026",
                DATABASE="db_tmdb_movie_dev",
            )
            glue_mock.start_job_run.assert_called_once_with(
                JobName="details-job",
                Arguments={
                    "--MEDIA_TYPE": "movie",
                    "--YEAR": "2025",
                    "--END_YEAR": "2026",
                    "--DATABASE": "db_tmdb_movie_dev",
                },
            )
