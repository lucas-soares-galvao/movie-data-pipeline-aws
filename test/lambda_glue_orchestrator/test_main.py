from unittest.mock import MagicMock, patch

import main

EVENTO = {
    "wait_for": [
        {"job_name": "tmdb-glue-etl-prod", "run_id": "run-genre"},
        {"job_name": "tmdb-glue-etl-prod", "run_id": "run-config"},
        {"job_name": "tmdb-glue-etl-prod", "run_id": "run-watch-ref"},
    ],
    "target_job_name": "tmdb-glue-agg-prod",
}


def _run(event: dict) -> dict:
    mock_context = MagicMock()
    with (
        patch("main.wait_for_job_runs") as mock_wait,
        patch("main.trigger_glue_job") as mock_trigger,
        patch("main.boto3") as mock_boto3,
    ):
        result = main.lambda_handler(event, mock_context)

    return {
        "result": result,
        "mock_wait": mock_wait,
        "mock_trigger": mock_trigger,
        "mock_boto3": mock_boto3,
    }


class TestLambdaHandler:
    def test_espera_os_jobs_de_wait_for(self):
        mocks = _run(EVENTO)
        mocks["mock_wait"].assert_called_once()
        glue_client_arg, wait_for_arg = mocks["mock_wait"].call_args[0]
        assert wait_for_arg == EVENTO["wait_for"]

    def test_usa_cliente_glue(self):
        mocks = _run(EVENTO)
        mocks["mock_boto3"].client.assert_called_once_with("glue")

    def test_aciona_target_job_name_apos_esperar(self):
        mocks = _run(EVENTO)
        mocks["mock_trigger"].assert_called_once_with("tmdb-glue-agg-prod")

    def test_repassa_target_job_args_quando_informado(self):
        evento = {**EVENTO, "target_job_args": {"YEAR": 2025}}
        mocks = _run(evento)
        mocks["mock_trigger"].assert_called_once_with("tmdb-glue-agg-prod", YEAR=2025)

    def test_retorna_status_200(self):
        mocks = _run(EVENTO)
        assert mocks["result"]["statusCode"] == 200
        assert "tmdb-glue-agg-prod" in mocks["result"]["body"]

    def test_ordem_espera_antes_de_acionar(self):
        """wait_for_job_runs precisa ser chamado antes de trigger_glue_job — senão o job
        alvo poderia rodar antes dos jobs em wait_for terminarem."""
        chamadas = []
        with (
            patch("main.wait_for_job_runs", side_effect=lambda *a: chamadas.append("wait")) as mock_wait,
            patch("main.trigger_glue_job", side_effect=lambda *a, **k: chamadas.append("trigger")) as mock_trigger,
            patch("main.boto3"),
        ):
            main.lambda_handler(EVENTO, MagicMock())

        assert chamadas == ["wait", "trigger"]
        mock_wait.assert_called_once()
        mock_trigger.assert_called_once()
