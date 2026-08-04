from unittest.mock import MagicMock, call, patch

from src.utils import wait_for_job_runs


def _job_run(state: str) -> dict:
    return {"JobRun": {"JobRunState": state}}


class TestWaitForJobRuns:
    def test_consulta_get_job_run_para_cada_item_de_wait_for(self):
        client = MagicMock()
        client.get_job_run.return_value = _job_run("SUCCEEDED")
        wait_for = [
            {"job_name": "job-a", "run_id": "run-1"},
            {"job_name": "job-b", "run_id": "run-2"},
        ]

        wait_for_job_runs(client, wait_for)

        assert client.get_job_run.call_args_list == [
            call(JobName="job-a", RunId="run-1"),
            call(JobName="job-b", RunId="run-2"),
        ]

    def test_faz_polling_ate_estado_terminal(self):
        client = MagicMock()
        client.get_job_run.side_effect = [
            _job_run("RUNNING"),
            _job_run("RUNNING"),
            _job_run("SUCCEEDED"),
        ]

        with patch("src.utils.time.sleep") as mock_sleep:
            wait_for_job_runs(client, [{"job_name": "job-a", "run_id": "run-1"}])

        assert client.get_job_run.call_count == 3
        assert mock_sleep.call_count == 2

    def test_nao_levanta_excecao_quando_job_falha(self):
        """Um job em FAILED não deve interromper a espera pelos demais."""
        client = MagicMock()
        client.get_job_run.side_effect = [_job_run("FAILED"), _job_run("SUCCEEDED")]
        wait_for = [
            {"job_name": "job-a", "run_id": "run-1"},
            {"job_name": "job-b", "run_id": "run-2"},
        ]

        wait_for_job_runs(client, wait_for)  # não deve levantar

        assert client.get_job_run.call_count == 2

    def test_loga_erro_quando_job_nao_termina_em_succeeded(self, caplog):
        client = MagicMock()
        client.get_job_run.return_value = _job_run("TIMEOUT")

        with caplog.at_level("ERROR"):
            wait_for_job_runs(client, [{"job_name": "job-a", "run_id": "run-1"}])

        assert any("TIMEOUT" in r.message for r in caplog.records)

    def test_lista_vazia_nao_chama_get_job_run(self):
        client = MagicMock()

        wait_for_job_runs(client, [])

        client.get_job_run.assert_not_called()
