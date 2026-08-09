"""
Testa scripts/backfill_shared.py com boto3 mockado (nenhuma chamada real à AWS).

Foco: contrato de load/save/clear de checkpoint usado pelos 4 scripts de
backfill que iteram por ano, para permitir retomada automática após
credencial AWS expirada (`ExpiredTokenException` do STS ou `ExpiredToken` do
S3); e os helpers de env var, guard de custo de tradução, range de anos,
wrapper de retry e mensagem de progresso do checkpoint.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import backfill_shared as bs
import pytest
from botocore.exceptions import ClientError

# trigger_agg_locally importa app.glue_agg.src.utils dentro da própria função (import local —
# ver docstring), inserindo app/glue_agg em sys.path antes (necessário por causa do "from
# src.queries import ..." absoluto em app/glue_agg/src/utils.py). test/scripts/ não passa pelo
# mecanismo de alias de test/conftest.py (só cobre os diretórios de suite Glue em
# _SUITE_TO_APP) — sem este import antecipado, testar via patch("app.glue_agg.src.utils.X")
# falharia com ModuleNotFoundError: No module named 'src' na primeira importação da suíte.
sys.path.insert(0, str(bs._REPO_ROOT / "app" / "shared_src"))
sys.path.insert(0, str(bs._REPO_ROOT / "app" / "glue_agg"))
import app.glue_agg.src.utils as _glue_agg_utils  # noqa: E402


def _client_error(codigo: str) -> ClientError:
    return ClientError({"Error": {"Code": codigo, "Message": codigo}}, "S3Op")


class TestSaoPauloConverter:
    def test_converte_utc_para_horario_de_sao_paulo(self):
        # 2024-01-15T12:00:00Z — período pós-2019 (Brasil sem horário de
        # verão), America/Sao_Paulo é UTC-3 fixo nessa janela.
        timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()

        result = bs._sao_paulo_converter(timestamp)

        assert (result.tm_year, result.tm_mon, result.tm_mday) == (2024, 1, 15)
        assert (result.tm_hour, result.tm_min, result.tm_sec) == (9, 0, 0)

    def test_formatter_usa_o_converter_de_sao_paulo(self):
        assert logging.Formatter.converter is bs._sao_paulo_converter

    def test_asctime_sai_no_formato_dd_mm_yyyy(self):
        # Formatter isolado (não usa logging.getLogger().handlers[0]): sob pytest
        # o root logger tem o LogCaptureHandler do próprio pytest, com formatter
        # e datefmt independentes dos configurados em backfill_shared.
        formatter = logging.Formatter(datefmt="%d/%m/%Y %H:%M:%S")
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
        record.created = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()

        assert formatter.formatTime(record, formatter.datefmt) == "15/01/2024 09:00:00"


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


class TestApplyTranslateCostGuard:
    def test_mantem_aws_para_intervalo_de_1_ano(self):
        assert bs.apply_translate_cost_guard("aws", 2020, 2020) == "aws"

    def test_rebaixa_aws_para_google_em_intervalo_maior_que_1_ano(self):
        assert bs.apply_translate_cost_guard("aws", 2020, 2021) == "google"

    def test_nao_mexe_quando_ja_e_google(self):
        assert bs.apply_translate_cost_guard("google", 2000, 2025) == "google"

    def test_loga_aviso_quando_rebaixa(self, caplog):
        with caplog.at_level("WARNING", logger="backfill_shared"):
            bs.apply_translate_cost_guard("aws", 2020, 2025)

        assert any("rebaixando" in r.message for r in caplog.records)


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


class TestTriggerAggLocally:
    """trigger_agg_locally importa run_athena_query/write_parquet_to_spec/trigger_glue_job de
    app.glue_agg.src.utils dentro da própria função (import local, ver docstring) — por isso os
    testes patcham os símbolos na origem (app.glue_agg.src.utils.*), não em backfill_shared.*.
    """

    _KWARGS = dict(
        s3_bucket_spec="bucket-spec-test",
        s3_prefix_spec="tmdb",
        s3_bucket_temp="bucket-temp-test",
        db_movie="db_movie",
        db_tv="db_tv",
        db_unified="db_unified",
        table_name="tb_discover_unified",
        dq_job_name="dq-job",
        environment="dev",
    )

    def test_caminho_feliz_chama_query_escrita_e_dq_na_ordem_certa(self):
        manager = MagicMock()
        with (
            patch.object(_glue_agg_utils, "run_athena_query", return_value="df-fake") as mock_query,
            patch.object(_glue_agg_utils, "write_parquet_to_spec") as mock_write,
            patch.object(_glue_agg_utils, "trigger_glue_job") as mock_trigger,
        ):
            manager.attach_mock(mock_query, "query")
            manager.attach_mock(mock_write, "write")
            manager.attach_mock(mock_trigger, "trigger")
            bs.trigger_agg_locally(**self._KWARGS)

        mock_query.assert_called_once_with(
            db_movie="db_movie", db_tv="db_tv", db_unified="db_unified",
            s3_bucket_temp="bucket-temp-test", env="dev",
        )
        mock_write.assert_called_once_with(
            df="df-fake", s3_bucket_spec="bucket-spec-test", s3_prefix_spec="tmdb",
            table_name="tb_discover_unified", database="db_unified",
        )
        mock_trigger.assert_called_once_with(
            "dq-job", TABLE_NAME="tb_discover_unified", DATABASE="db_unified",
        )
        ordem = [c[0] for c in manager.mock_calls]
        assert ordem == ["query", "write", "trigger"]

    def test_client_error_nao_token_expirado_e_logado_e_nao_propaga(self, caplog):
        with (
            patch.object(_glue_agg_utils, "run_athena_query", side_effect=_client_error("ThrottlingException")),
            caplog.at_level("ERROR", logger="backfill_shared"),
        ):
            bs.trigger_agg_locally(**self._KWARGS)

        assert any("Falha ao rodar o Glue AGG localmente" in r.message for r in caplog.records)

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_client_error_token_expirado_propaga(self, codigo, caplog):
        with (
            patch.object(_glue_agg_utils, "run_athena_query", side_effect=_client_error(codigo)),
            caplog.at_level("ERROR", logger="backfill_shared"),
            pytest.raises(ClientError),
        ):
            bs.trigger_agg_locally(**self._KWARGS)

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    def test_excecao_generica_e_logada_e_nao_propaga(self, caplog):
        with (
            patch.object(_glue_agg_utils, "run_athena_query", return_value="df-fake"),
            patch.object(_glue_agg_utils, "write_parquet_to_spec", side_effect=RuntimeError("sem arquivos")),
            patch.object(_glue_agg_utils, "trigger_glue_job") as mock_trigger,
            caplog.at_level("ERROR", logger="backfill_shared"),
        ):
            bs.trigger_agg_locally(**self._KWARGS)

        assert any("Falha ao rodar o Glue AGG localmente" in r.message for r in caplog.records)
        mock_trigger.assert_not_called()


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
