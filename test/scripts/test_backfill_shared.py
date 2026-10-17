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
from datetime import date, datetime, timezone
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

# resolve_pending_units_by_year importa get_api_secret de shared_utils.api_client dentro
# da própria função (import local, ver docstring) — precisa do sys.path.insert acima já
# feito antes desta importação, mesmo motivo do import de app.glue_agg.src.utils abaixo.
import shared_utils.api_client as _api_client_module

import app.glue_agg.src.utils as _glue_agg_utils


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


class TestSetupLogging:
    def test_mascara_segredos_nos_handlers_do_logger_raiz(self):
        """A saída dos scripts vai ao log do Actions (público, num repositório público) e ao step
        summary: a api_key do TMDB, embutida na URL de uma exceção do requests, nunca pode aparecer."""
        import io

        from shared_utils.secret_redaction import RedactingFormatter

        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root.addHandler(handler)
        try:
            assert bs.setup_logging() is root
            assert isinstance(handler.formatter, RedactingFormatter)
            root.warning("404 for url: https://api.themoviedb.org/3/x?api_key=0123456789abcdef0123456789abcdef")
        finally:
            root.removeHandler(handler)
        assert "0123456789abcdef0123456789abcdef" not in stream.getvalue()
        assert "api_key=***" in stream.getvalue()


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

    def test_envia_expected_bucket_owner_quando_conta_definida(self, monkeypatch):
        """ExpectedBucketOwner (ver _expected_bucket_owner_kwargs) protege contra bucket squatting."""
        monkeypatch.setenv("AWS_ACCOUNT_ID", "123456789012")
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2000, "end_year": 2025, "completed": []}
        )

        bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert client.get_object.call_args.kwargs["ExpectedBucketOwner"] == "123456789012"

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

    def test_envia_expected_bucket_owner_quando_conta_definida(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCOUNT_ID", "123456789012")
        client = MagicMock()

        bs.save_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025, set())

        assert client.put_object.call_args.kwargs["ExpectedBucketOwner"] == "123456789012"

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        client = MagicMock()
        client.put_object.side_effect = _client_error(codigo)

        with caplog.at_level("ERROR", logger="backfill_shared"):
            with pytest.raises(ClientError):
                bs.save_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025, set())

        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestReprocessAllEnabled:
    @pytest.mark.parametrize("valor, esperado", [(None, False), ("", False), ("false", False), ("true", True), ("TRUE", True)])
    def test_le_backfill_reprocess_all(self, monkeypatch, valor, esperado):
        if valor is None:
            monkeypatch.delenv("BACKFILL_REPROCESS_ALL", raising=False)
        else:
            monkeypatch.setenv("BACKFILL_REPROCESS_ALL", valor)

        assert bs.reprocess_all_enabled() is esperado


class TestModoDoCheckpoint:
    """Um checkpoint só é reaproveitado por um run do mesmo modo (normal x Reprocessar tudo):
    senão o "Reprocessar tudo" herdaria unidades de um run normal anterior e as pularia."""

    def test_run_normal_nao_grava_a_chave_mode(self, monkeypatch):
        monkeypatch.delenv("BACKFILL_REPROCESS_ALL", raising=False)
        client = MagicMock()

        bs.save_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025, {"movie:2000"})

        assert "mode" not in json.loads(client.put_object.call_args.kwargs["Body"])

    def test_reprocessar_tudo_grava_mode_reprocess_all(self, monkeypatch):
        monkeypatch.setenv("BACKFILL_REPROCESS_ALL", "true")
        client = MagicMock()

        bs.save_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025, {"movie:2000"})

        assert json.loads(client.put_object.call_args.kwargs["Body"])["mode"] == "reprocess_all"

    def test_reprocessar_tudo_ignora_checkpoint_de_run_normal(self, monkeypatch, caplog):
        monkeypatch.setenv("BACKFILL_REPROCESS_ALL", "true")
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2000, "end_year": 2025, "completed": ["movie:2000"]}
        )

        with caplog.at_level("WARNING", logger="backfill_shared"):
            completed = bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert completed == set()
        assert any("modo 'normal'" in r.message and "'reprocess_all'" in r.message for r in caplog.records)

    def test_reprocessar_tudo_retoma_checkpoint_do_mesmo_modo(self, monkeypatch):
        """Retry por token expirado e novo disparo após timeout continuam retomando."""
        monkeypatch.setenv("BACKFILL_REPROCESS_ALL", "true")
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2000, "end_year": 2025, "completed": ["movie:2000"], "mode": "reprocess_all"}
        )

        completed = bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025)

        assert completed == {"movie:2000"}

    def test_run_normal_ignora_checkpoint_de_reprocessar_tudo(self, monkeypatch):
        monkeypatch.delenv("BACKFILL_REPROCESS_ALL", raising=False)
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2000, "end_year": 2025, "completed": ["movie:2000"], "mode": "reprocess_all"}
        )

        assert bs.load_checkpoint(client, "bucket", "detalhes_e_providers", 2000, 2025) == set()


class TestReportStaleProcessedDate:
    _RUN_START = date(2026, 10, 17)

    def _df(self, rows: list[tuple[int, date]]):
        import pandas as pd

        return pd.DataFrame({"id": [r[0] for r in rows], "processed_date": [r[1] for r in rows]})

    def _run(self, read_side_effect, tables=("tb_movie",), years=(2020,)):
        with patch("awswrangler.s3.read_parquet", side_effect=read_side_effect) as mock_read:
            total = bs.report_stale_processed_date(
                tables=list(tables), s3_bucket_sot="sot", years=list(years), run_start_date=self._RUN_START,
            )
        return total, mock_read

    def test_todos_rebuscados_nao_loga_erro(self, caplog):
        df = self._df([(1, date(2026, 10, 17)), (2, date(2026, 10, 18))])

        with caplog.at_level("INFO", logger="backfill_shared"):
            total, _ = self._run([df])

        assert total == 0
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("foram reprocessados" in r.message for r in caplog.records)

    def test_registro_com_data_anterior_e_listado_como_erro(self, caplog):
        df = self._df([(1, date(2026, 10, 17)), (2, date(2026, 10, 10)), (3, date(2025, 1, 1))])

        with caplog.at_level("ERROR", logger="backfill_shared"):
            total, _ = self._run([df])

        assert total == 2
        detalhe = next(r.message for r in caplog.records if "NÃO foram rebuscados" in r.message)
        assert "'tb_movie' year=2020" in detalhe
        assert "2, 3" in detalhe
        assert any("2 registro(s) no total" in r.message for r in caplog.records)

    def test_limita_os_ids_de_exemplo(self, caplog):
        df = self._df([(i, date(2020, 1, 1)) for i in range(20)])

        with caplog.at_level("ERROR", logger="backfill_shared"):
            self._run([df])

        detalhe = next(r.message for r in caplog.records if "NÃO foram rebuscados" in r.message)
        assert detalhe.endswith("0, 1, 2, 3, 4")

    def test_soma_tabelas_e_anos_e_filtra_a_particao_certa(self):
        dfs = [self._df([(1, date(2020, 1, 1))]), self._df([]), self._df([(2, date(2020, 1, 1))]), self._df([])]

        total, mock_read = self._run(dfs, tables=("tb_movie", "tb_tv"), years=(2020, 2021))

        assert total == 2
        assert mock_read.call_count == 4
        assert mock_read.call_args_list[0].kwargs["path"] == "s3://sot/tmdb/tb_movie/"
        assert mock_read.call_args_list[0].kwargs["columns"] == ["id", "processed_date"]
        particao = mock_read.call_args_list[0].kwargs["partition_filter"]
        assert particao({"year": "2020"}) is True
        assert particao({"year": "2021"}) is False

    def test_particao_inexistente_e_ignorada(self):
        total, _ = self._run([Exception("sem partição")])

        assert total == 0

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_token_expirado_propaga(self, codigo):
        erro = _client_error(codigo)

        with pytest.raises(ClientError):
            self._run([erro])

    def test_outro_client_error_e_tratado_como_particao_inexistente(self):
        total, _ = self._run([_client_error("AccessDenied")])

        assert total == 0


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
    def test_chama_delete_object_com_a_chave_correta(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCOUNT_ID", raising=False)
        client = MagicMock()

        bs.clear_checkpoint(client, "bucket", "detalhes_e_providers")

        client.delete_object.assert_called_once_with(
            Bucket="bucket", Key="tmdb/backfill_checkpoints/detalhes_e_providers.json"
        )

    def test_envia_expected_bucket_owner_quando_conta_definida(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCOUNT_ID", "123456789012")
        client = MagicMock()

        bs.clear_checkpoint(client, "bucket", "detalhes_e_providers")

        assert client.delete_object.call_args.kwargs["ExpectedBucketOwner"] == "123456789012"

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


class TestExpectedBucketOwnerKwargs:
    def test_retorna_kwarg_quando_aws_account_id_definida(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCOUNT_ID", "123456789012")
        assert bs._expected_bucket_owner_kwargs() == {"ExpectedBucketOwner": "123456789012"}

    def test_retorna_vazio_quando_ausente(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCOUNT_ID", raising=False)
        assert bs._expected_bucket_owner_kwargs() == {}

    def test_retorna_vazio_quando_vazia(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCOUNT_ID", "")
        assert bs._expected_bucket_owner_kwargs() == {}


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


class TestSessionBudgetLow:
    """Guarda que evita iniciar uma unidade longa quando a sessão AWS de 1h está perto do fim."""

    @staticmethod
    def _sessao_com(monkeypatch, decorrido: float, duracao: str | None = "3600") -> None:
        """Simula `decorrido` segundos desde o início do processo e a duração da sessão."""
        import time

        monkeypatch.setattr(bs, "_PROCESS_START", time.monotonic() - decorrido)
        if duracao is None:
            monkeypatch.delenv(bs.SESSION_SECONDS_ENV, raising=False)
        else:
            monkeypatch.setenv(bs.SESSION_SECONDS_ENV, duracao)

    def test_desligada_sem_a_variavel_de_sessao(self, monkeypatch):
        """Execução local não tem workflow para renovar a credencial: nunca deve sair com 75."""
        self._sessao_com(monkeypatch, decorrido=99999, duracao=None)
        assert bs.session_budget_low(1000) is False

    def test_sem_estimativa_a_primeira_unidade_sempre_roda(self, monkeypatch):
        """Garante progresso: toda tentativa conclui ao menos uma unidade."""
        self._sessao_com(monkeypatch, decorrido=99999)
        assert bs.session_budget_low(0) is False

    def test_sessao_com_folga_suficiente_nao_sinaliza(self, monkeypatch):
        self._sessao_com(monkeypatch, decorrido=1000)  # restam ~2300s após a folga
        assert bs.session_budget_low(1000) is False

    def test_tempo_restante_menor_que_a_maior_unidade_sinaliza(self, monkeypatch):
        """Caso do run 39042448970: 3ª unidade (~1000s) iniciada com ~17min de sessão."""
        self._sessao_com(monkeypatch, decorrido=2600)  # restam ~700s após a folga
        assert bs.session_budget_low(1000) is True

    def test_folga_de_seguranca_entra_na_conta(self, monkeypatch):
        """Restam 3600-3000=600s: sobraria para uma unidade de 500s, mas não com a folga de 300s."""
        self._sessao_com(monkeypatch, decorrido=3000)
        assert bs.session_budget_low(500) is True

    def test_exit_if_session_budget_low_sai_com_codigo_75_e_loga(self, monkeypatch, caplog):
        self._sessao_com(monkeypatch, decorrido=2600)
        with caplog.at_level(logging.WARNING), pytest.raises(SystemExit) as exc_info:
            bs.exit_if_session_budget_low(1000)
        assert exc_info.value.code == bs.RETRYABLE_EXIT_CODE
        assert any("Sessão AWS sem tempo" in r.message for r in caplog.records)

    def test_exit_if_session_budget_low_nao_sai_quando_ha_tempo(self, monkeypatch):
        self._sessao_com(monkeypatch, decorrido=10)
        bs.exit_if_session_budget_low(1000)  # não levanta SystemExit


class TestResolvePendingUnitsByYear:
    """resolve_pending_units_by_year importa get_api_secret de shared_utils.api_client
    dentro da própria função (import local, mesmo racional de trigger_agg_locally) — por
    isso os testes patcham o símbolo na origem (shared_utils.api_client.*), não em
    backfill_shared.*."""

    def _kwargs(self, s3_client: MagicMock) -> dict:
        return dict(
            label="discover",
            start_year=2020,
            end_year=2021,
            db_movie="db_movie",
            db_tv="db_tv",
            secret_arn="arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb",
            s3_client=s3_client,
            s3_bucket_temp="bucket-temp-test",
            table_group="discover",
        )

    def test_busca_api_key_com_o_secret_arn_recebido(self):
        client = MagicMock()
        client.get_object.side_effect = _client_error("NoSuchKey")
        with patch.object(_api_client_module, "get_api_secret", return_value="tmdb-key") as mock_secret:
            _, api_key, *_ = bs.resolve_pending_units_by_year(**self._kwargs(client))

        mock_secret.assert_called_once_with(
            "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb", "tmdb_api_key",
        )
        assert api_key == "tmdb-key"

    def test_years_e_unidades_pendentes_sem_checkpoint(self):
        client = MagicMock()
        client.get_object.side_effect = _client_error("NoSuchKey")
        with patch.object(_api_client_module, "get_api_secret", return_value="tmdb-key"):
            years, _, completed, pendentes = bs.resolve_pending_units_by_year(**self._kwargs(client))

        assert years == [2020, 2021]
        assert completed == set()
        assert pendentes == [
            ("movie", 2020, "db_movie"), ("tv", 2020, "db_tv"),
            ("movie", 2021, "db_movie"), ("tv", 2021, "db_tv"),
        ]

    def test_unidades_do_checkpoint_saem_de_pendentes(self):
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2020, "end_year": 2021, "completed": ["movie:2020"]}
        )
        with patch.object(_api_client_module, "get_api_secret", return_value="tmdb-key"):
            _, _, completed, pendentes = bs.resolve_pending_units_by_year(**self._kwargs(client))

        assert completed == {"movie:2020"}
        assert ("movie", 2020, "db_movie") not in pendentes
        assert ("tv", 2020, "db_tv") in pendentes

    def test_loga_progresso_do_checkpoint(self, caplog):
        client = MagicMock()
        client.get_object.return_value = _get_object_response(
            {"start_year": 2020, "end_year": 2021, "completed": ["movie:2020"]}
        )
        with (
            patch.object(_api_client_module, "get_api_secret", return_value="tmdb-key"),
            caplog.at_level("INFO"),
        ):
            bs.resolve_pending_units_by_year(**self._kwargs(client))

        assert any("retomando com 3 pendente(s)" in r.message for r in caplog.records)


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


class TestNotifyBackfillSuccess:
    """notify_backfill_success é a última etapa de um script já concluído com sucesso — por
    isso nunca propaga exceção (nem token expirado, diferente de trigger_agg_locally): deixar
    propagar forçaria run_with_retry_exit a sinalizar exit 75 e reprocessar o backfill inteiro
    do zero só por causa de uma falha de observabilidade (ver docstring da função)."""

    def test_publica_com_topic_arn_subject_e_message_corretos(self, monkeypatch):
        monkeypatch.setenv("SNS_TOPIC_ARN_BACKFILL_SUCCESS", "arn:aws:sns:sa-east-1:123456789:backfill-success")
        monkeypatch.setenv("ENVIRONMENT", "dev")
        with patch("backfill_shared.boto3") as mock_boto3:
            mock_sns = MagicMock()
            mock_boto3.client.return_value = mock_sns

            bs.notify_backfill_success("discover", "resumo do backfill")

        mock_boto3.client.assert_called_once_with("sns")
        mock_sns.publish.assert_called_once_with(
            TopicArn="arn:aws:sns:sa-east-1:123456789:backfill-success",
            Subject="[DEV] BACKFILL - SUCESSO",
            Message="resumo do backfill",
        )

    def test_loga_warning_e_nao_publica_quando_env_var_ausente(self, monkeypatch, caplog):
        monkeypatch.delenv("SNS_TOPIC_ARN_BACKFILL_SUCCESS", raising=False)
        with patch("backfill_shared.boto3") as mock_boto3:
            with caplog.at_level("WARNING", logger="backfill_shared"):
                bs.notify_backfill_success("discover", "resumo do backfill")

        mock_boto3.client.assert_not_called()
        assert any("não enviada" in r.message for r in caplog.records)

    def test_engole_excecao_generica_do_publish_sem_propagar(self, monkeypatch, caplog):
        monkeypatch.setenv("SNS_TOPIC_ARN_BACKFILL_SUCCESS", "arn:aws:sns:sa-east-1:123456789:backfill-success")
        with patch("backfill_shared.boto3") as mock_boto3:
            mock_sns = MagicMock()
            mock_sns.publish.side_effect = RuntimeError("sns indisponível")
            mock_boto3.client.return_value = mock_sns

            with caplog.at_level("ERROR", logger="backfill_shared"):
                bs.notify_backfill_success("discover", "resumo do backfill")  # não deve levantar

        assert any("Falha ao publicar notificação" in r.message for r in caplog.records)

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_engole_client_error_de_token_expirado_sem_propagar(self, monkeypatch, caplog, codigo):
        """Diferente das demais chamadas AWS do backfill (que repropagam token expirado para
        run_with_retry_exit traduzir em exit 75), aqui até token expirado é engolido — esta
        função roda depois de clear_checkpoint na maioria dos scripts."""
        monkeypatch.setenv("SNS_TOPIC_ARN_BACKFILL_SUCCESS", "arn:aws:sns:sa-east-1:123456789:backfill-success")
        with patch("backfill_shared.boto3") as mock_boto3:
            mock_sns = MagicMock()
            mock_sns.publish.side_effect = _client_error(codigo)
            mock_boto3.client.return_value = mock_sns

            with caplog.at_level("ERROR", logger="backfill_shared"):
                bs.notify_backfill_success("discover", "resumo do backfill")  # não deve levantar

        assert any("Falha ao publicar notificação" in r.message for r in caplog.records)


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
