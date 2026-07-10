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
    "TABLE_GROUP": "discover",
    "S3_BUCKET_TEMP": "bucket-temp-test",
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


def _s3_client_sem_checkpoint() -> MagicMock:
    """Cliente S3 mockado simulando ausência de checkpoint (comportamento padrão nos testes)."""
    client = MagicMock()
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject",
    )
    return client


def _run_main(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None, mock_s3: MagicMock | None = None):
    """Roda bh.main() com boto3 e time.sleep mockados. Retorna (mock_lambda, mock_sleep, mock_s3)."""
    _set_env(monkeypatch, overrides)
    mock_lambda = MagicMock()
    mock_lambda.invoke.return_value = _lambda_ok_response()
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()

    def _client_factory(service_name, **kwargs):
        return {"lambda": mock_lambda, "s3": mock_s3}[service_name]

    with (
        patch("backfill_historico.boto3") as mock_boto3,
        patch("backfill_historico.time.sleep") as mock_sleep,
    ):
        mock_boto3.client.side_effect = _client_factory
        bh.main()
    return mock_lambda, mock_sleep, mock_s3


def _payloads(mock_client: MagicMock) -> list[dict]:
    return [json.loads(c.kwargs["Payload"]) for c in mock_client.invoke.call_args_list]


class TestContratoDoPayload:
    """Garante que o payload usa exatamente as flags que o lambda_handler reconhece."""

    def test_envia_only_annual_tables(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for payload in _payloads(mock_client):
            assert payload["only_annual_tables"] is True

    def test_nao_envia_mais_a_chave_only_discover(self, monkeypatch):
        """Regressão: only_discover nunca foi lida pelo lambda_handler (bug corrigido)."""
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for payload in _payloads(mock_client):
            assert "only_discover" not in payload

    def test_inclui_tabelas_de_referencia_exigidas_pelo_lambda_handler(self, monkeypatch):
        """lambda_handler acessa event['table_genre_movie'] etc. sem .get() — removê-las quebra com KeyError."""
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        payload_movie = _payloads(mock_client)[0]
        assert payload_movie["table_genre_movie"] == "genre_movie"
        assert payload_movie["table_configuration_languages"] == "config_languages"
        assert payload_movie["table_watch_providers_ref_movie"] == "watch_ref_movie"

    def test_start_year_igual_loop_end_year_uma_particao_por_invocacao(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        for payload in _payloads(mock_client):
            assert payload["start_year"] == payload["loop_end_year"]


class TestLoopDeAnos:
    def test_invoca_lambda_duas_vezes_por_ano_movie_e_tv(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_client.invoke.call_count == 6  # 3 anos x 2 tipos

    def test_alterna_movie_e_tv_na_ordem_por_ano(self, monkeypatch):
        mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        tipos = [p["type"] for p in _payloads(mock_client)]
        assert tipos == ["movie", "tv"]

    def test_usa_ano_atual_como_default_de_end_year(self, monkeypatch):
        with patch("backfill_shared.datetime") as mock_dt:
            mock_dt.now.return_value.year = 2030
            mock_dt.now.return_value.isoformat.return_value = "2030-01-01T00:00:00+00:00"
            mock_client, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2030"})
        assert mock_client.invoke.call_count == 2


class TestPausaEntreInvocacoes:
    def test_nao_pausa_apos_ultima_invocacao(self, monkeypatch):
        mock_client, mock_sleep, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_sleep.call_count == mock_client.invoke.call_count - 1


class TestErros:
    def test_erro_da_lambda_interrompe_o_backfill(self, monkeypatch):
        _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        mock_client = MagicMock()
        mock_client.invoke.return_value = {
            "StatusCode": 500,
            "Payload": MagicMock(read=MagicMock(return_value=b'{"errorMessage": "falhou"}')),
        }
        mock_s3 = _s3_client_sem_checkpoint()

        def _client_factory(service_name, **kwargs):
            return {"lambda": mock_client, "s3": mock_s3}[service_name]

        with (
            patch("backfill_historico.boto3") as mock_boto3,
            patch("backfill_historico.time.sleep"),
            pytest.raises(RuntimeError),
        ):
            mock_boto3.client.side_effect = _client_factory
            bh.main()

    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("LAMBDA_FUNCTION_NAME", raising=False)
        with pytest.raises(EnvironmentError):
            bh.main()

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.invoke.side_effect = ClientError(
            {"Error": {"Code": codigo, "Message": "expired"}}, "Invoke",
        )
        with caplog.at_level("ERROR", logger="backfill_historico"):
            with pytest.raises(ClientError):
                bh.shared.invoke_lambda_sync(client, "func", {"a": 1})
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_no_topo_sai_com_codigo_75(self, monkeypatch, codigo):
        _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        mock_client = MagicMock()
        mock_client.invoke.side_effect = ClientError(
            {"Error": {"Code": codigo, "Message": "expired"}}, "Invoke",
        )
        mock_s3 = _s3_client_sem_checkpoint()

        def _client_factory(service_name, **kwargs):
            return {"lambda": mock_client, "s3": mock_s3}[service_name]

        with (
            patch("backfill_historico.boto3") as mock_boto3,
            patch("backfill_historico.time.sleep"),
        ):
            mock_boto3.client.side_effect = _client_factory
            try:
                bh.main()
            except ClientError as exc:
                codigo = bh.shared.expired_token_exit_code(exc)
                assert codigo == 75
            else:
                pytest.fail("esperava ClientError propagado de main()")

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "Invoke")
        assert bh.shared.expired_token_exit_code(exc) is None


class TestAssertSingleYear:
    def test_lanca_erro_quando_anos_diferentes(self):
        with pytest.raises(ValueError):
            bh._assert_single_year({"start_year": 2020, "loop_end_year": 2021})

    def test_nao_lanca_erro_quando_anos_iguais(self):
        bh._assert_single_year({"start_year": 2020, "loop_end_year": 2020})


class TestCheckpoint:
    def test_pula_unidades_ja_concluidas(self, monkeypatch):
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=json.dumps(
                {"start_year": 2020, "end_year": 2021, "completed": ["movie:2020", "tv:2020"]}
            ).encode()))
        }

        mock_client, _, _ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"}, mock_s3=mock_s3,
        )

        tipos_anos = [(p["type"], p["start_year"]) for p in _payloads(mock_client)]
        assert tipos_anos == [("movie", 2021), ("tv", 2021)]

    def test_salva_checkpoint_apos_cada_unidade(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        assert mock_s3.put_object.call_count == 2  # movie:2020, tv:2020

    def test_limpa_checkpoint_ao_concluir_tudo_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        mock_s3.delete_object.assert_called_once()

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_checkpoint_reflete_progresso_parcial_quando_interrompido(self, monkeypatch, codigo):
        _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        mock_lambda = MagicMock()
        mock_lambda.invoke.side_effect = [
            _lambda_ok_response(),  # movie:2020 sucede
            ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "Invoke"),  # tv:2020 falha
        ]
        mock_s3 = _s3_client_sem_checkpoint()

        def _client_factory(service_name, **kwargs):
            return {"lambda": mock_lambda, "s3": mock_s3}[service_name]

        with (
            patch("backfill_historico.boto3") as mock_boto3,
            patch("backfill_historico.time.sleep"),
            pytest.raises(ClientError),
        ):
            mock_boto3.client.side_effect = _client_factory
            bh.main()

        assert mock_s3.put_object.call_count == 1
        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["movie:2020"]
