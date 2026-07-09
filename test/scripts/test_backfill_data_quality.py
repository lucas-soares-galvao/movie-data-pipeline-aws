"""
Testa scripts/backfill_data_quality.py com boto3 mockado (nenhuma chamada real à AWS).

Foco: argumentos enviados ao Glue Data Quality job e o contrato "assíncrono,
fire-and-forget" — diferente de backfill_enriquecimento.py, este script nunca
espera o job terminar (não deve chamar get_job_run).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import backfill_data_quality as bdq

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "GLUE_DATA_QUALITY_JOB_NAME": "tmdb-glue-dq-test",
    "TABLE_GROUP": "data_quality",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_DISCOVER_MOVIE": "discover_movie",
    "TABLE_DISCOVER_TV": "discover_tv",
    "TABLE_DETAILS_MOVIE": "details_movie",
    "TABLE_DETAILS_TV": "details_tv",
    "TABLE_WATCH_PROVIDERS_MOVIE": "watch_providers_movie",
    "TABLE_WATCH_PROVIDERS_TV": "watch_providers_tv",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> None:
    for key, value in {**ENV_BASE, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


def _s3_client_sem_checkpoint() -> MagicMock:
    """Cliente S3 mockado simulando ausência de checkpoint (comportamento padrão nos testes)."""
    client = MagicMock()
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject",
    )
    return client


class TestTriggerDqJob:
    def test_argumentos_enviados_ao_glue(self):
        client = MagicMock()
        client.start_job_run.return_value = {"JobRunId": "run-1"}

        run_id = bdq._trigger_dq_job(client, "job", "discover_movie", "db_movie", "2020")

        assert run_id == "run-1"
        client.start_job_run.assert_called_once_with(
            JobName="job",
            Arguments={"--TABLE_NAME": "discover_movie", "--DATABASE": "db_movie", "--YEAR": "2020"},
        )

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.start_job_run.side_effect = ClientError(
            {"Error": {"Code": codigo, "Message": "expired"}}, "StartJobRun",
        )
        with caplog.at_level("ERROR", logger="backfill_data_quality"):
            with pytest.raises(ClientError):
                bdq._trigger_dq_job(client, "job", "discover_movie", "db_movie", "2020")
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


def _run_main(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None, mock_s3: MagicMock | None = None):
    _set_env(monkeypatch, overrides)
    mock_glue = MagicMock()
    mock_glue.start_job_run.side_effect = [{"JobRunId": f"run-{i}"} for i in range(1000)]
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()

    def _client_factory(service_name, **kwargs):
        return {"glue": mock_glue, "s3": mock_s3}[service_name]

    with (
        patch("backfill_data_quality.boto3") as mock_boto3,
        patch("backfill_data_quality.time.sleep") as mock_sleep,
    ):
        mock_boto3.client.side_effect = _client_factory
        bdq.main()
    return mock_glue, mock_sleep, mock_s3


class TestLoopPrincipal:
    def test_total_de_execucoes_e_anos_vezes_seis_tabelas(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_client.start_job_run.call_count == 12  # 2 anos x 6 tabelas

    def test_percorre_as_seis_tabelas_dentro_de_cada_ano(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        tabelas = [c.kwargs["Arguments"]["--TABLE_NAME"] for c in mock_client.start_job_run.call_args_list]
        assert tabelas == [
            "discover_movie", "discover_tv", "details_movie",
            "details_tv", "watch_providers_movie", "watch_providers_tv",
        ]

    def test_e_assincrono_nunca_espera_o_job_terminar(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        mock_client.get_job_run.assert_not_called()

    def test_pausa_entre_anos_mas_nao_apos_o_ultimo(self, monkeypatch):
        mock_client, mock_sleep, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_sleep.call_count == 2  # 3 anos -> pausa após ano 1 e ano 2, não após o 3º

    def test_wait_zero_desativa_a_pausa(self, monkeypatch):
        _, mock_sleep, _ = _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022", "WAIT_SECONDS": "0"},
        )
        mock_sleep.assert_not_called()


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("TABLE_WATCH_PROVIDERS_TV", raising=False)
        with pytest.raises(EnvironmentError):
            bdq.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "StartJobRun")
        assert bdq.checkpoint.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "StartJobRun")
        assert bdq.checkpoint.expired_token_exit_code(exc) == 75


class TestCheckpoint:
    def test_pula_execucoes_ja_concluidas(self, monkeypatch):
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=json.dumps(
                {
                    "start_year": 2020, "end_year": 2020,
                    "completed": ["discover_movie:2020", "discover_tv:2020"],
                }
            ).encode()))
        }

        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        tabelas = [c.kwargs["Arguments"]["--TABLE_NAME"] for c in mock_client.start_job_run.call_args_list]
        assert tabelas == ["details_movie", "details_tv", "watch_providers_movie", "watch_providers_tv"]

    def test_salva_checkpoint_apos_cada_submissao(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        assert mock_s3.put_object.call_count == 6

    def test_limpa_checkpoint_ao_concluir_tudo_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        mock_s3.delete_object.assert_called_once()

    def test_nao_pausa_quando_ano_inteiro_ja_esta_no_checkpoint(self, monkeypatch):
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=json.dumps(
                {
                    "start_year": 2020, "end_year": 2021,
                    "completed": [
                        "discover_movie:2020", "discover_tv:2020", "details_movie:2020",
                        "details_tv:2020", "watch_providers_movie:2020", "watch_providers_tv:2020",
                    ],
                }
            ).encode()))
        }

        _, mock_sleep, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"}, mock_s3=mock_s3)

        mock_sleep.assert_not_called()
