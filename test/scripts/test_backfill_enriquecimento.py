"""
Testa scripts/backfill_enriquecimento.py com boto3 mockado (nenhuma chamada real à AWS).

Foco: argumentos enviados ao Glue Details job, o polling de conclusão e o
contrato "erro em um run não aborta o backfill inteiro" — diferente de
backfill_historico.py, que interrompe tudo no primeiro erro.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import backfill_enriquecimento as be

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "GLUE_DETAILS_JOB_NAME": "tmdb-glue-details-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> None:
    for key, value in {**ENV_BASE, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


class TestStartGlueJob:
    def test_argumentos_padrao_sem_force_refetch(self):
        client = MagicMock()
        client.start_job_run.return_value = {"JobRunId": "run-1"}

        run_id = be._start_glue_job(client, "job", "movie", 2020, 2025, "db_movie")

        assert run_id == "run-1"
        args = client.start_job_run.call_args.kwargs["Arguments"]
        assert args == {"--MEDIA_TYPE": "movie", "--YEAR": "2020", "--END_YEAR": "2025", "--DATABASE": "db_movie"}

    def test_inclui_force_refetch_quando_true(self):
        client = MagicMock()
        client.start_job_run.return_value = {"JobRunId": "run-2"}

        be._start_glue_job(client, "job", "tv", 2021, 2025, "db_tv", force_refetch=True)

        args = client.start_job_run.call_args.kwargs["Arguments"]
        assert args["--FORCE_REFETCH"] == "true"


class TestWaitForJob:
    def test_retorna_imediatamente_quando_ja_terminou(self):
        client = MagicMock()
        client.get_job_run.return_value = {"JobRun": {"JobRunState": "SUCCEEDED"}}

        estado = be._wait_for_job(client, "job", "run-1")

        assert estado == "SUCCEEDED"
        client.get_job_run.assert_called_once()

    def test_faz_polling_ate_estado_terminal(self):
        client = MagicMock()
        client.get_job_run.side_effect = [
            {"JobRun": {"JobRunState": "RUNNING"}},
            {"JobRun": {"JobRunState": "RUNNING"}},
            {"JobRun": {"JobRunState": "FAILED"}},
        ]

        with patch("backfill_enriquecimento.time.sleep") as mock_sleep:
            estado = be._wait_for_job(client, "job", "run-1", poll_interval=10)

        assert estado == "FAILED"
        assert client.get_job_run.call_count == 3
        mock_sleep.assert_called_with(10)

    def test_propaga_expired_token_com_log_claro(self, caplog):
        client = MagicMock()
        client.get_job_run.side_effect = ClientError(
            {"Error": {"Code": "ExpiredTokenException", "Message": "The security token included in the request is expired"}},
            "GetJobRun",
        )

        with caplog.at_level("ERROR", logger="backfill_enriquecimento"):
            with pytest.raises(ClientError):
                be._wait_for_job(client, "job", "run-1")

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    def test_propaga_outros_client_error_sem_log_de_credenciais(self, caplog):
        client = MagicMock()
        client.get_job_run.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "GetJobRun",
        )

        with caplog.at_level("ERROR", logger="backfill_enriquecimento"):
            with pytest.raises(ClientError):
                be._wait_for_job(client, "job", "run-1")

        assert not any("Credenciais AWS expiraram" in r.message for r in caplog.records)


def _run_main(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None, job_states=None):
    """Roda be.main() com o client Glue mockado. job_states define o resultado de cada _wait_for_job."""
    _set_env(monkeypatch, overrides)
    mock_client = MagicMock()
    mock_client.start_job_run.side_effect = [
        {"JobRunId": f"run-{i}"} for i in range(1000)
    ]
    with (
        patch("backfill_enriquecimento.boto3") as mock_boto3,
        patch("backfill_enriquecimento.time.sleep") as mock_sleep,
        patch("backfill_enriquecimento._wait_for_job") as mock_wait,
    ):
        mock_boto3.client.return_value = mock_client
        mock_wait.side_effect = job_states or (lambda *a, **k: "SUCCEEDED")
        be.main()
    return mock_client, mock_sleep, mock_wait


class TestLoopPrincipal:
    def test_total_de_runs_e_anos_vezes_dois_tipos(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_client.start_job_run.call_count == 6  # 3 anos x 2 tipos

    def test_roda_todos_os_anos_de_movie_antes_de_tv(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        media_types = [c.kwargs["Arguments"]["--MEDIA_TYPE"] for c in mock_client.start_job_run.call_args_list]
        assert media_types == ["movie", "movie", "tv", "tv"]

    def test_falha_em_um_run_nao_interrompe_o_backfill(self, monkeypatch):
        """Diferente de backfill_historico.py: um estado != SUCCEEDED aqui só é logado, não aborta o loop."""
        mock_client, _, _ = _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"},
            job_states=["FAILED", "SUCCEEDED", "SUCCEEDED", "SUCCEEDED"],
        )
        assert mock_client.start_job_run.call_count == 4

    def test_nao_pausa_apos_ultimo_run(self, monkeypatch):
        mock_client, mock_sleep, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_sleep.call_count == mock_client.start_job_run.call_count - 1

    def test_loga_resumo_das_falhas_ao_final(self, monkeypatch, caplog):
        with caplog.at_level("ERROR", logger="backfill_enriquecimento"):
            _run_main(
                monkeypatch,
                {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"},
                job_states=["FAILED", "SUCCEEDED", "SUCCEEDED", "TIMEOUT"],
            )
        resumo = [r.message for r in caplog.records if "precisam ser re-executados" in r.message]
        assert len(resumo) == 1
        assert "movie/2020 (FAILED)" in resumo[0]
        assert "tv/2021 (TIMEOUT)" in resumo[0]

    def test_nao_loga_resumo_quando_tudo_sucede(self, monkeypatch, caplog):
        with caplog.at_level("ERROR", logger="backfill_enriquecimento"):
            _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        resumo = [r.message for r in caplog.records if "precisam ser re-executados" in r.message]
        assert resumo == []


class TestForceRefetch:
    def test_default_e_true(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        args = mock_client.start_job_run.call_args_list[0].kwargs["Arguments"]
        assert args["--FORCE_REFETCH"] == "true"

    def test_false_omite_o_argumento(self, monkeypatch):
        mock_client, _, _ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020", "FORCE_REFETCH": "false"}
        )
        args = mock_client.start_job_run.call_args_list[0].kwargs["Arguments"]
        assert "--FORCE_REFETCH" not in args


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("GLUE_DETAILS_JOB_NAME", raising=False)
        with pytest.raises(EnvironmentError):
            be.main()
