"""
Testa scripts/backfill_enriquecimento.py com run_details_and_watch_providers_for_year/
get_api_secret/trigger_glue_job mockados (nenhuma chamada real à AWS/TMDB).

Foco: a lógica de negócio de enriquecimento em si é testada em
test/glue_details/test_utils.py::TestRunDetailsAndWatchProvidersForYear — aqui o foco é
a orquestração do backfill: quais unidades são processadas, o contrato "erro em uma
unidade não aborta o backfill inteiro" (soft-fail-continue, diferente de
backfill_historico.py, que interrompe tudo no primeiro erro), o checkpoint, e o disparo
único do Glue Data Quality ao final cobrindo todo o range de anos.
"""

import json
from unittest.mock import MagicMock, call, patch

import backfill_enriquecimento as be
import pytest
from botocore.exceptions import ClientError

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "TABLE_GROUP": "detalhes_e_providers",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "S3_BUCKET_TEMP": "bucket-temp-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_DISCOVER_MOVIE": "tb_discover_movie",
    "TABLE_DISCOVER_TV": "tb_discover_tv",
    "TABLE_DETAILS_MOVIE": "tb_details_movie",
    "TABLE_DETAILS_TV": "tb_details_tv",
    "TABLE_WATCH_PROVIDERS_MOVIE": "tb_wp_movie",
    "TABLE_WATCH_PROVIDERS_TV": "tb_wp_tv",
    "TMDB_SECRET_ARN": "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb",
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
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


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict | None = None,
    unit_side_effect=None,
    mock_s3: MagicMock | None = None,
):
    """Roda be.main() com run_details_and_watch_providers_for_year/trigger_glue_job mockados.

    unit_side_effect define o comportamento de run_details_and_watch_providers_for_year por
    unidade — lista de exceções/None (na ordem das unidades pendentes) ou uma função.
    """
    _set_env(monkeypatch, overrides)
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()

    with (
        patch("backfill_enriquecimento.boto3") as mock_boto3,
        patch("backfill_enriquecimento.time.sleep") as mock_sleep,
        patch("backfill_enriquecimento.get_api_secret", return_value="tmdb-key") as mock_secret,
        patch("backfill_enriquecimento.run_details_and_watch_providers_for_year") as mock_run,
        patch("backfill_enriquecimento.trigger_glue_job") as mock_trigger,
    ):
        mock_boto3.client.return_value = mock_s3
        if unit_side_effect is not None:
            mock_run.side_effect = unit_side_effect
        be.main()
    return mock_run, mock_sleep, mock_s3, mock_secret, mock_trigger


class TestLoopPrincipal:
    def test_total_de_unidades_e_anos_vezes_dois_tipos(self, monkeypatch):
        mock_run, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_run.call_count == 6  # 3 anos x 2 tipos

    def test_intercala_movie_e_tv_por_ano(self, monkeypatch):
        mock_run, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        media_types = [c.kwargs["media_type"] for c in mock_run.call_args_list]
        assert media_types == ["movie", "tv", "movie", "tv"]

    def test_passa_trigger_dq_false_para_nao_disparar_dq_por_unidade(self, monkeypatch):
        mock_run, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for c in mock_run.call_args_list:
            assert c.kwargs["trigger_dq"] is False

    def test_falha_em_uma_unidade_nao_interrompe_o_backfill(self, monkeypatch):
        """Diferente de backfill_historico.py: uma exceção aqui só é logada, não aborta o loop."""
        mock_run, *_ = _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"},
            unit_side_effect=[Exception("boom"), None, None, None],
        )
        assert mock_run.call_count == 4

    def test_nao_pausa_apos_ultima_unidade(self, monkeypatch):
        mock_run, mock_sleep, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        # WAIT_SECONDS default (15) entre unidades, mais 4 sleeps do disparo final de DQ (um por tabela)
        assert mock_sleep.call_count == (mock_run.call_count - 1) + 4

    def test_loga_resumo_das_falhas_ao_final(self, monkeypatch, caplog):
        with caplog.at_level("ERROR", logger="backfill_enriquecimento"):
            _run_main(
                monkeypatch,
                {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"},
                unit_side_effect=[Exception("falhou movie 2020"), None, None, Exception("falhou tv 2021")],
            )
        resumo = [r.message for r in caplog.records if "precisam ser re-executadas" in r.message]
        assert len(resumo) == 1
        assert "movie/2020" in resumo[0]
        assert "tv/2021" in resumo[0]

    def test_nao_loga_resumo_quando_tudo_sucede(self, monkeypatch, caplog):
        with caplog.at_level("ERROR", logger="backfill_enriquecimento"):
            _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        resumo = [r.message for r in caplog.records if "precisam ser re-executadas" in r.message]
        assert resumo == []

    def test_translate_provider_default_google_propagado(self, monkeypatch):
        mock_run, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        assert mock_run.call_args_list[0].kwargs["translate_provider"] == "google"

    def test_translate_provider_aws_propagado(self, monkeypatch):
        mock_run, *_ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020", "TRANSLATE_PROVIDER": "aws"}
        )
        assert mock_run.call_args_list[0].kwargs["translate_provider"] == "aws"

    def test_translate_provider_aws_rebaixado_para_google_em_intervalo_maior_que_1_ano(self, monkeypatch):
        """Proteção de custo: aws só é aceito para um intervalo de 1 ano — ver
        backfill_shared.apply_translate_cost_guard."""
        mock_run, *_ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021", "TRANSLATE_PROVIDER": "aws"}
        )
        for c in mock_run.call_args_list:
            assert c.kwargs["translate_provider"] == "google"

    def test_busca_api_key_uma_unica_vez_fora_do_loop(self, monkeypatch):
        _, _, _, mock_secret, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        mock_secret.assert_called_once_with(
            "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb", "tmdb_api_key"
        )

    def test_api_key_repassada_para_cada_unidade(self, monkeypatch):
        mock_run, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for c in mock_run.call_args_list:
            assert c.kwargs["api_key"] == "tmdb-key"


class TestForceRefetch:
    def test_default_e_true(self, monkeypatch):
        mock_run, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        assert mock_run.call_args_list[0].kwargs["force_refetch"] is True

    def test_false_explicito(self, monkeypatch):
        mock_run, *_ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020", "FORCE_REFETCH": "false"}
        )
        assert mock_run.call_args_list[0].kwargs["force_refetch"] is False


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("TMDB_SECRET_ARN", raising=False)
        with pytest.raises(EnvironmentError):
            be.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetSecretValue")
        assert be.shared.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "GetSecretValue")
        assert be.shared.expired_token_exit_code(exc) == 75

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_token_expirado_em_uma_unidade_propaga_sem_ser_capturado_como_falha_soft(self, monkeypatch, codigo):
        """Token expirado precisa propagar (para o run_with_retry_exit tratar como exit 75),
        não ser tratado como falha soft-fail-continue de uma unidade qualquer."""
        exc = ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "StartQueryExecution")
        with pytest.raises(ClientError):
            _run_main(
                monkeypatch,
                {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
                unit_side_effect=[exc],
            )


class TestCheckpoint:
    def test_pula_unidades_ja_concluidas(self, monkeypatch):
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=json.dumps(
                {"start_year": 2020, "end_year": 2021, "completed": ["movie:2020", "movie:2021"]}
            ).encode()))
        }

        mock_run, *_ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"}, mock_s3=mock_s3,
        )

        pendentes = [(c.kwargs["media_type"], c.kwargs["year"]) for c in mock_run.call_args_list]
        assert pendentes == [("tv", "2020"), ("tv", "2021")]

    def test_salva_checkpoint_apenas_para_unidades_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
            unit_side_effect=[Exception("falhou"), None],
            mock_s3=mock_s3,
        )

        assert mock_s3.put_object.call_count == 1
        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["tv:2020"]

    def test_limpa_checkpoint_ao_concluir_tudo_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        mock_s3.delete_object.assert_called_once()

    def test_nao_limpa_checkpoint_quando_ha_falhas(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
            unit_side_effect=[Exception("falhou"), None],
            mock_s3=mock_s3,
        )

        mock_s3.delete_object.assert_not_called()


class TestDataQualityFinal:
    def test_dispara_dq_uma_vez_por_tabela_cobrindo_o_range_completo(self, monkeypatch):
        _, _, _, _, mock_trigger = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})

        assert mock_trigger.call_count == 4
        assert call("dq-job", TABLE_NAME="tb_details_movie", DATABASE="db_movie", YEAR="2020,2021") in mock_trigger.call_args_list
        assert call("dq-job", TABLE_NAME="tb_details_tv", DATABASE="db_tv", YEAR="2020,2021") in mock_trigger.call_args_list
        assert call("dq-job", TABLE_NAME="tb_wp_movie", DATABASE="db_movie", YEAR="2020,2021") in mock_trigger.call_args_list
        assert call("dq-job", TABLE_NAME="tb_wp_tv", DATABASE="db_tv", YEAR="2020,2021") in mock_trigger.call_args_list

    def test_nao_dispara_dq_quando_ha_falhas(self, monkeypatch):
        _, _, _, _, mock_trigger = _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
            unit_side_effect=[Exception("falhou"), None],
        )
        mock_trigger.assert_not_called()
