"""
Testa scripts/backfill_shared.py com boto3 mockado (nenhuma chamada real à AWS).

Foco: contrato de load/save/clear de checkpoint usado pelos 4 scripts de
backfill que iteram por ano, para permitir retomada automática após
credencial AWS expirada (`ExpiredTokenException` do STS ou `ExpiredToken` do
S3); e os helpers de env var, invocação de Lambda, payloads base, range de
anos, wrapper de retry e mensagem de progresso do checkpoint.
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import backfill_shared as bs


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

        completed = bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert completed == set()

    def test_checkpoint_compativel_retorna_completed(self):
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2000, "end_year": 2025, "completed": ["movie:2000", "tv:2000"]}
        )

        completed = bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert completed == {"movie:2000", "tv:2000"}

    def test_checkpoint_range_incompativel_retorna_vazio_e_loga_aviso(self, caplog):
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2000, "end_year": 2020, "completed": ["movie:2000"]}
        )

        with caplog.at_level("WARNING", logger="backfill_shared"):
            completed = bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert completed == set()
        assert any("range incompatível" in r.message for r in caplog.records)

    def test_outro_client_error_e_repropagado(self):
        client = MagicMock()
        client.get_object.side_effect = _client_error("AccessDenied")

        with pytest.raises(ClientError):
            bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.get_object.side_effect = _client_error(codigo)

        with caplog.at_level("ERROR", logger="backfill_shared"):
            with pytest.raises(ClientError):
                bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestSaveCheckpoint:
    def test_grava_json_esperado(self):
        client = MagicMock()

        bs.save_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025, {"tv:2001", "movie:2000"})

        args = client.put_object.call_args.kwargs
        assert args["Bucket"] == "bucket"
        assert args["Key"] == "tmdb/backfill_checkpoints/detalhes_e_providers.json"
        body = json.loads(args["Body"])
        assert body["start_year"] == 2000
        assert body["end_year"] == 2025
        assert body["completed"] == ["movie:2000", "tv:2001"]
        assert "updated_at" in body

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.put_object.side_effect = _client_error(codigo)

        with caplog.at_level("ERROR", logger="backfill_shared"):
            with pytest.raises(ClientError):
                bs.save_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025, set())

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestIsExpiredTokenError:
    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_codigos_de_token_expirado_retornam_true(self, codigo):
        assert bs.is_expired_token_error(_client_error(codigo)) is True

    @pytest.mark.parametrize("codigo", ["ThrottlingException", "AccessDenied"])
    def test_outros_codigos_retornam_false(self, codigo):
        assert bs.is_expired_token_error(_client_error(codigo)) is False


class TestExpiredTokenExitCode:
    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_retorna_codigo_retomavel(self, codigo):
        exc = _client_error(codigo)

        assert bs.expired_token_exit_code(exc) == bs.RETRYABLE_EXIT_CODE

    def test_outro_erro_retorna_none(self):
        exc = _client_error("ThrottlingException")

        assert bs.expired_token_exit_code(exc) is None


class TestClearCheckpoint:
    def test_chama_delete_object_com_a_chave_correta(self):
        client = MagicMock()

        bs.clear_checkpoint(client, "bucket", "detalhes_e_providers")

        client.delete_object.assert_called_once_with(
            Bucket="bucket", Key="tmdb/backfill_checkpoints/detalhes_e_providers.json"
        )

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.delete_object.side_effect = _client_error(codigo)

        with caplog.at_level("ERROR", logger="backfill_shared"):
            with pytest.raises(ClientError):
                bs.clear_checkpoint(client, "bucket", "detalhes_e_providers")

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestRequireEnv:
    def test_retorna_valor_quando_definida(self, monkeypatch):
        monkeypatch.setenv("MINHA_VAR", "valor")
        assert bs.require_env("MINHA_VAR") == "valor"

    def test_lanca_erro_quando_ausente(self, monkeypatch):
        monkeypatch.delenv("MINHA_VAR", raising=False)
        with pytest.raises(EnvironmentError):
            bs.require_env("MINHA_VAR")

    def test_lanca_erro_quando_vazia(self, monkeypatch):
        monkeypatch.setenv("MINHA_VAR", "")
        with pytest.raises(EnvironmentError):
            bs.require_env("MINHA_VAR")


class TestInvokeLambdaSync:
    def _ok_response(self) -> dict:
        payload = MagicMock()
        payload.read.return_value = json.dumps({"body": "ok"}).encode()
        return {"StatusCode": 200, "Payload": payload}

    def test_sucesso_nao_lanca_erro(self):
        client = MagicMock()
        client.invoke.return_value = self._ok_response()

        bs.invoke_lambda_sync(client, "func", {"a": 1})

        client.invoke.assert_called_once()

    def test_status_diferente_de_200_lanca_runtime_error(self):
        client = MagicMock()
        client.invoke.return_value = {
            "StatusCode": 500,
            "Payload": MagicMock(read=MagicMock(return_value=b'{"errorMessage": "falhou"}')),
        }
        with pytest.raises(RuntimeError):
            bs.invoke_lambda_sync(client, "func", {"a": 1})

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.invoke.side_effect = _client_error(codigo)

        with caplog.at_level("ERROR", logger="backfill_shared"):
            with pytest.raises(ClientError):
                bs.invoke_lambda_sync(client, "func", {"a": 1})

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestBuildBasePayloads:
    ENV = {
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

    def test_monta_base_movie_e_base_tv(self, monkeypatch):
        for key, value in self.ENV.items():
            monkeypatch.setenv(key, value)

        base_movie, base_tv = bs.build_base_payloads()

        assert base_movie["type"] == "movie"
        assert base_movie["database"] == "db_movie"
        assert base_movie["table_genre_movie"] == "genre_movie"
        assert base_tv["type"] == "tv"
        assert base_tv["database"] == "db_tv"
        assert base_tv["table_genre_tv"] == "genre_tv"

    def test_variavel_ausente_lanca_erro(self, monkeypatch):
        for key, value in self.ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("GLUE_DATABASE_MOVIE", raising=False)

        with pytest.raises(EnvironmentError):
            bs.build_base_payloads()


class TestReadYearRange:
    def test_usa_defaults_quando_env_ausente(self, monkeypatch):
        monkeypatch.delenv("BACKFILL_START_YEAR", raising=False)
        monkeypatch.delenv("BACKFILL_END_YEAR", raising=False)
        with patch("backfill_shared.datetime") as mock_dt:
            mock_dt.now.return_value.year = 2030
            start_year, end_year = bs.read_year_range()

        assert start_year == 2000
        assert end_year == 2030

    def test_le_env_vars_quando_definidas(self, monkeypatch):
        monkeypatch.setenv("BACKFILL_START_YEAR", "2010")
        monkeypatch.setenv("BACKFILL_END_YEAR", "2015")

        assert bs.read_year_range() == (2010, 2015)

    def test_aceita_nomes_de_env_var_customizados(self, monkeypatch):
        monkeypatch.delenv("BACKFILL_START_YEAR", raising=False)
        monkeypatch.setenv("MEU_START", "1999")
        monkeypatch.setenv("BACKFILL_END_YEAR", "2005")

        assert bs.read_year_range(start_env="MEU_START") == (1999, 2005)


class TestRunWithRetryExit:
    def test_sucesso_nao_sai_do_processo(self):
        main_fn = MagicMock()
        bs.run_with_retry_exit(main_fn)
        main_fn.assert_called_once()

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_token_expirado_sai_com_codigo_75(self, codigo):
        main_fn = MagicMock(side_effect=_client_error(codigo))
        with pytest.raises(SystemExit) as exc_info:
            bs.run_with_retry_exit(main_fn)
        assert exc_info.value.code == bs.RETRYABLE_EXIT_CODE

    def test_outro_client_error_repropaga(self):
        main_fn = MagicMock(side_effect=_client_error("ThrottlingException"))
        with pytest.raises(ClientError):
            bs.run_with_retry_exit(main_fn)


class TestLogResumeProgress:
    def test_loga_quando_ha_unidades_ja_concluidas(self, caplog):
        logger = logging.getLogger("test_log_resume_progress")
        with caplog.at_level("INFO", logger="test_log_resume_progress"):
            bs.log_resume_progress(logger, "runs já concluídos", total=10, pendentes=7)

        assert any("3 de 10 runs já concluídos" in r.message for r in caplog.records)
        assert any("7 pendente(s)" in r.message for r in caplog.records)

    def test_nao_loga_quando_nao_ha_progresso_salvo(self, caplog):
        logger = logging.getLogger("test_log_resume_progress_sem_progresso")
        with caplog.at_level("INFO", logger="test_log_resume_progress_sem_progresso"):
            bs.log_resume_progress(logger, "runs já concluídos", total=10, pendentes=10)

        assert caplog.records == []
