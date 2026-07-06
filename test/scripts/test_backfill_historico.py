"""
Testa scripts/backfill_historico.py com boto3 mockado (nenhuma chamada real à AWS).

Foco: contrato do payload enviado à Lambda. O bug corrigido neste script
(chave "only_discover", nunca lida por app/lambda_api/main.py, deveria ser
"only_annual_tables") só seria percebido rodando um backfill real de horas
contra prod — daí o valor de travar esse contrato em teste.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import backfill_historico as bh

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


def _run_main(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None):
    """Roda bh.main() com boto3 e time.sleep mockados. Retorna (mock_client, mock_sleep)."""
    _set_env(monkeypatch, overrides)
    mock_client = MagicMock()
    mock_client.invoke.return_value = _lambda_ok_response()
    with (
        patch("backfill_historico.boto3") as mock_boto3,
        patch("backfill_historico.time.sleep") as mock_sleep,
    ):
        mock_boto3.client.return_value = mock_client
        bh.main()
    return mock_client, mock_sleep


def _payloads(mock_client: MagicMock) -> list[dict]:
    return [json.loads(c.kwargs["Payload"]) for c in mock_client.invoke.call_args_list]


class TestContratoDoPayload:
    """Garante que o payload usa exatamente as flags que o lambda_handler reconhece."""

    def test_envia_only_annual_tables(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for payload in _payloads(mock_client):
            assert payload["only_annual_tables"] is True

    def test_nao_envia_mais_a_chave_only_discover(self, monkeypatch):
        """Regressão: only_discover nunca foi lida pelo lambda_handler (bug corrigido)."""
        mock_client, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for payload in _payloads(mock_client):
            assert "only_discover" not in payload

    def test_inclui_tabelas_de_referencia_exigidas_pelo_lambda_handler(self, monkeypatch):
        """lambda_handler acessa event['table_genre_movie'] etc. sem .get() — removê-las quebra com KeyError."""
        mock_client, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        payload_movie = _payloads(mock_client)[0]
        assert payload_movie["table_genre_movie"] == "genre_movie"
        assert payload_movie["table_configuration_languages"] == "config_languages"
        assert payload_movie["table_watch_providers_ref_movie"] == "watch_ref_movie"

    def test_start_year_igual_loop_end_year_uma_particao_por_invocacao(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        for payload in _payloads(mock_client):
            assert payload["start_year"] == payload["loop_end_year"]


class TestLoopDeAnos:
    def test_invoca_lambda_duas_vezes_por_ano_movie_e_tv(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_client.invoke.call_count == 6  # 3 anos x 2 tipos

    def test_alterna_movie_e_tv_na_ordem_por_ano(self, monkeypatch):
        mock_client, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        tipos = [p["type"] for p in _payloads(mock_client)]
        assert tipos == ["movie", "tv"]

    def test_usa_ano_atual_como_default_de_end_year(self, monkeypatch):
        with patch("backfill_historico.datetime") as mock_dt:
            mock_dt.now.return_value.year = 2030
            mock_client, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2030"})
        assert mock_client.invoke.call_count == 2


class TestPausaEntreInvocacoes:
    def test_nao_pausa_apos_ultima_invocacao(self, monkeypatch):
        mock_client, mock_sleep = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_sleep.call_count == mock_client.invoke.call_count - 1


class TestErros:
    def test_erro_da_lambda_interrompe_o_backfill(self, monkeypatch):
        _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        mock_client = MagicMock()
        mock_client.invoke.return_value = {
            "StatusCode": 500,
            "Payload": MagicMock(read=MagicMock(return_value=b'{"errorMessage": "falhou"}')),
        }
        with (
            patch("backfill_historico.boto3") as mock_boto3,
            patch("backfill_historico.time.sleep"),
            pytest.raises(RuntimeError),
        ):
            mock_boto3.client.return_value = mock_client
            bh.main()

    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("LAMBDA_FUNCTION_NAME", raising=False)
        with pytest.raises(EnvironmentError):
            bh.main()

    def test_expired_token_loga_e_repropaga(self, caplog):
        client = MagicMock()
        client.invoke.side_effect = ClientError(
            {"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "Invoke",
        )
        with caplog.at_level("ERROR", logger="backfill_historico"):
            with pytest.raises(ClientError):
                bh._invoke(client, "func", {"a": 1})
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestAssertSingleYear:
    def test_lanca_erro_quando_anos_diferentes(self):
        with pytest.raises(ValueError):
            bh._assert_single_year({"start_year": 2020, "loop_end_year": 2021})

    def test_nao_lanca_erro_quando_anos_iguais(self):
        bh._assert_single_year({"start_year": 2020, "loop_end_year": 2020})
