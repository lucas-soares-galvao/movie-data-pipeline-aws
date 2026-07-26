"""
Testa scripts/backfill_changes.py com boto3 mockado (nenhuma chamada real à AWS).

Foco: contrato do payload enviado à Lambda em modo only_changes_tables — o mesmo
modo que o EventBridge já aciona automaticamente todo domingo. Este script não
aceita nem calcula datas: a janela [hoje - 8 dias, hoje] é sempre resolvida dentro
de collect_changes_data (app/lambda_api/src/utils.py).
"""

import json
from unittest.mock import MagicMock, patch

import backfill_changes as bc
import pytest

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "LAMBDA_FUNCTION_NAME": "tmdb-lambda-api-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> None:
    for key, value in {**ENV_BASE, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


def _lambda_ok_response() -> dict:
    payload = MagicMock()
    payload.read.return_value = json.dumps({"body": "ok"}).encode()
    return {"StatusCode": 200, "Payload": payload}


def _run_main(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None):
    """Roda bc.main() com boto3 e time.sleep mockados. Retorna (mock_client, mock_sleep)."""
    _set_env(monkeypatch, overrides)
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_ok_response()
    with (
        patch("backfill_changes.boto3") as mock_boto3,
        patch("backfill_changes.time.sleep") as mock_sleep,
    ):
        mock_boto3.client.return_value = mock_client
        bc.main()
    return mock_client, mock_sleep


def _payloads(mock_client: MagicMock) -> list[dict]:
    return [json.loads(c.kwargs["Payload"]) for c in mock_client.invoke.call_args_list]


class TestContratoDoPayload:
    def test_envia_only_changes_tables(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch)
        for payload in _payloads(mock_client):
            assert payload["only_changes_tables"] is True

    def test_payload_nao_contem_chaves_de_tabela(self, monkeypatch):
        """O modo changes de main.py sai cedo, antes de acessar event['table_*'] — payload deve ser mínimo."""
        mock_client, _ = _run_main(monkeypatch)
        for payload in _payloads(mock_client):
            assert not any(chave.startswith("table_") for chave in payload)

    def test_payload_nao_contem_datas(self, monkeypatch):
        """Regressão: este script nunca deve enviar changes_start_date/changes_end_date."""
        mock_client, _ = _run_main(monkeypatch)
        for payload in _payloads(mock_client):
            assert "changes_start_date" not in payload
            assert "changes_end_date" not in payload

    def test_database_correto_por_content_type(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch)
        payloads = {p["type"]: p for p in _payloads(mock_client)}
        assert payloads["movie"]["database"] == "db_movie"
        assert payloads["tv"]["database"] == "db_tv"

    def test_translate_provider_default_google(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch)
        for payload in _payloads(mock_client):
            assert payload["translate_provider"] == "google"

    def test_translate_provider_repassado_quando_informado(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch, {"TRANSLATE_PROVIDER": "aws"})
        for payload in _payloads(mock_client):
            assert payload["translate_provider"] == "aws"


class TestInvocacoes:
    def test_invoca_lambda_uma_vez_para_movie_e_uma_para_tv(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch)
        assert mock_client.invoke.call_count == 2
        tipos = [p["type"] for p in _payloads(mock_client)]
        assert tipos == ["movie", "tv"]

    def test_pausa_apenas_entre_as_duas_invocacoes(self, monkeypatch):
        mock_client, mock_sleep = _run_main(monkeypatch)
        assert mock_sleep.call_count == 1
        assert mock_client.invoke.call_count == 2


class TestErros:
    def test_erro_da_lambda_interrompe_o_backfill(self, monkeypatch):
        _set_env(monkeypatch)
        mock_client = MagicMock()
        mock_client.invoke.return_value = {
            "StatusCode": 500,
            "Payload": MagicMock(read=MagicMock(return_value=b'{"errorMessage": "falhou"}')),
        }
        with (
            patch("backfill_changes.boto3") as mock_boto3,
            patch("backfill_changes.time.sleep"),
            pytest.raises(RuntimeError),
        ):
            mock_boto3.client.return_value = mock_client
            bc.main()

    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("LAMBDA_FUNCTION_NAME", raising=False)
        with pytest.raises(EnvironmentError):
            bc.main()
