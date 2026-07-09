"""
Testa scripts/backfill_checkpoint.py com boto3 mockado (nenhuma chamada real à AWS).

Foco: contrato de load/save/clear usado pelos 4 scripts de backfill que
iteram por ano, para permitir retomada automática após credencial AWS
expirada (`ExpiredTokenException` do STS ou `ExpiredToken` do S3).
"""

import json
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

import backfill_checkpoint as bc


def _client_error(codigo: str) -> ClientError:
    return ClientError({"Error": {"Code": codigo, "Message": codigo}}, "S3Op")


def _get_object_response(data: dict) -> dict:
    body = MagicMock()
    body.read.return_value = json.dumps(data).encode()
    return {"Body": body}


class TestLoadCheckpoint:
    def test_sem_checkpoint_retorna_vazio(self):
        client = MagicMock()
        client.get_object.side_effect = _client_error("NoSuchKey")

        completed = bc.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert completed == set()

    def test_checkpoint_compativel_retorna_completed(self):
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2000, "end_year": 2025, "completed": ["movie:2000", "tv:2000"]}
        )

        completed = bc.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert completed == {"movie:2000", "tv:2000"}

    def test_checkpoint_range_incompativel_retorna_vazio_e_loga_aviso(self, caplog):
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2000, "end_year": 2020, "completed": ["movie:2000"]}
        )

        with caplog.at_level("WARNING", logger="backfill_checkpoint"):
            completed = bc.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert completed == set()
        assert any("range incompatível" in r.message for r in caplog.records)

    def test_outro_client_error_e_repropagado(self):
        client = MagicMock()
        client.get_object.side_effect = _client_error("AccessDenied")

        with pytest.raises(ClientError):
            bc.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.get_object.side_effect = _client_error(codigo)

        with caplog.at_level("ERROR", logger="backfill_checkpoint"):
            with pytest.raises(ClientError):
                bc.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestSaveCheckpoint:
    def test_grava_json_esperado(self):
        client = MagicMock()

        bc.save_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025, {"tv:2001", "movie:2000"})

        args = client.put_object.call_args.kwargs
        assert args["Bucket"] == "bucket"
        assert args["Key"] == "_backfill_checkpoints/detalhes_e_providers.json"
        body = json.loads(args["Body"])
        assert body["start_year"] == 2000
        assert body["end_year"] == 2025
        assert body["completed"] == ["movie:2000", "tv:2001"]
        assert "updated_at" in body

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.put_object.side_effect = _client_error(codigo)

        with caplog.at_level("ERROR", logger="backfill_checkpoint"):
            with pytest.raises(ClientError):
                bc.save_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025, set())

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestIsExpiredTokenError:
    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_codigos_de_token_expirado_retornam_true(self, codigo):
        assert bc.is_expired_token_error(_client_error(codigo)) is True

    @pytest.mark.parametrize("codigo", ["ThrottlingException", "AccessDenied"])
    def test_outros_codigos_retornam_false(self, codigo):
        assert bc.is_expired_token_error(_client_error(codigo)) is False


class TestExpiredTokenExitCode:
    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_retorna_codigo_retomavel(self, codigo):
        exc = _client_error(codigo)

        assert bc.expired_token_exit_code(exc) == bc.RETRYABLE_EXIT_CODE

    def test_outro_erro_retorna_none(self):
        exc = _client_error("ThrottlingException")

        assert bc.expired_token_exit_code(exc) is None


class TestClearCheckpoint:
    def test_chama_delete_object_com_a_chave_correta(self):
        client = MagicMock()

        bc.clear_checkpoint(client, "bucket", "detalhes_e_providers")

        client.delete_object.assert_called_once_with(
            Bucket="bucket", Key="_backfill_checkpoints/detalhes_e_providers.json"
        )

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.delete_object.side_effect = _client_error(codigo)

        with caplog.at_level("ERROR", logger="backfill_checkpoint"):
            with pytest.raises(ClientError):
                bc.clear_checkpoint(client, "bucket", "detalhes_e_providers")

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)
