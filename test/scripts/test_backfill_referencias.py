"""
Testa scripts/backfill_referencias.py com boto3 mockado (nenhuma chamada real à AWS).

Foco: contrato do payload enviado à Lambda. O bug corrigido neste script
(chave "skip_discover", nunca lida por app/lambda_api/main.py, deveria ser
"skip_weekly") fazia o script recoletar o discover do ano atual além das
referências — daí o valor de travar esse contrato em teste.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import backfill_referencias as br

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "LAMBDA_FUNCTION_NAME": "tmdb-lambda-api-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "GLUE_DATABASE_UNIFIED": "db_unified",
    "TABLE_DISCOVER_MOVIE": "discover_movie",
    "TABLE_GENRE_MOVIE": "genre_movie",
    "TABLE_CONFIGURATION_LANGUAGES": "config_languages",
    "TABLE_WATCH_PROVIDERS_REF_MOVIE": "watch_ref_movie",
    "TABLE_DISCOVER_TV": "discover_tv",
    "TABLE_GENRE_TV": "genre_tv",
    "TABLE_CONFIGURATION_COUNTRIES": "config_countries",
    "TABLE_WATCH_PROVIDERS_REF_TV": "watch_ref_tv",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> None:
    for key, value in {**ENV_BASE, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


def _lambda_ok_response() -> dict:
    payload = MagicMock()
    payload.read.return_value = json.dumps({"body": "ok"}).encode()
    return {"StatusCode": 200, "Payload": payload}


def _run_main(monkeypatch: pytest.MonkeyPatch, *, ano: int = 2026):
    """Roda br.main() com boto3, time.sleep e datetime mockados. Retorna (mock_client, mock_sleep)."""
    _set_env(monkeypatch)
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_ok_response()
    with (
        patch("backfill_referencias.boto3") as mock_boto3,
        patch("backfill_referencias.time.sleep") as mock_sleep,
        patch("backfill_referencias.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.year = ano
        mock_boto3.client.return_value = mock_client
        br.main()
    return mock_client, mock_sleep


def _payloads(mock_client: MagicMock) -> list[dict]:
    return [json.loads(c.kwargs["Payload"]) for c in mock_client.invoke.call_args_list]


class TestContratoDoPayload:
    """Garante que o payload usa exatamente a flag que o lambda_handler reconhece."""

    def test_envia_skip_weekly(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch)
        for payload in _payloads(mock_client):
            assert payload["skip_weekly"] is True

    def test_nao_envia_mais_a_chave_skip_discover(self, monkeypatch):
        """Regressão: skip_discover nunca foi lida pelo lambda_handler (bug corrigido)."""
        mock_client, _ = _run_main(monkeypatch)
        for payload in _payloads(mock_client):
            assert "skip_discover" not in payload

    def test_usa_ano_atual_em_start_year_e_end_year(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch, ano=2027)
        for payload in _payloads(mock_client):
            assert payload["start_year"] == 2027
            assert payload["end_year"] == 2027


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
            patch("backfill_referencias.boto3") as mock_boto3,
            patch("backfill_referencias.time.sleep"),
            pytest.raises(RuntimeError),
        ):
            mock_boto3.client.return_value = mock_client
            br.main()

    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("LAMBDA_FUNCTION_NAME", raising=False)
        with pytest.raises(EnvironmentError):
            br.main()
