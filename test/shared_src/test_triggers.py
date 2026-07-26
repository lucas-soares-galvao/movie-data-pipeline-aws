from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from shared_utils.triggers import trigger_glue_job


def _concurrent_runs_error():
    return ClientError(
        {"Error": {"Code": "ConcurrentRunsExceededException", "Message": "Concurrent runs exceeded."}},
        "StartJobRun",
    )


def _other_client_error():
    return ClientError(
        {"Error": {"Code": "EntityNotFoundException", "Message": "Job não existe."}},
        "StartJobRun",
    )


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

    def test_retries_on_concurrent_runs_exceeded(self):
        glue_mock = self._make_glue_mock(run_id="run-after-retry")
        glue_mock.start_job_run.side_effect = [
            _concurrent_runs_error(),
            _concurrent_runs_error(),
            {"JobRunId": "run-after-retry"},
        ]
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock), \
             patch("shared_utils.triggers.time.sleep") as sleep_mock:
            run_id = trigger_glue_job("dq-job", max_retries=5)
            assert run_id == "run-after-retry"
            assert glue_mock.start_job_run.call_count == 3
            assert sleep_mock.call_count == 2

    def test_raises_after_exhausting_retries_on_concurrent_runs_exceeded(self):
        glue_mock = self._make_glue_mock()
        glue_mock.start_job_run.side_effect = _concurrent_runs_error()
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock), \
             patch("shared_utils.triggers.time.sleep"):
            with pytest.raises(ClientError):
                trigger_glue_job("dq-job", max_retries=3)
            assert glue_mock.start_job_run.call_count == 3

    def test_raises_immediately_on_non_concurrency_error(self):
        glue_mock = self._make_glue_mock()
        glue_mock.start_job_run.side_effect = _other_client_error()
        with patch("shared_utils.triggers.boto3.client", return_value=glue_mock), \
             patch("shared_utils.triggers.time.sleep") as sleep_mock:
            with pytest.raises(ClientError):
                trigger_glue_job("dq-job", max_retries=5)
            assert glue_mock.start_job_run.call_count == 1
            sleep_mock.assert_not_called()
