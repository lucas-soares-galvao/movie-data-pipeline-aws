"""
Testa scripts/backfill_discover.py com collect_discover_data/read_from_sor/
write_parquet_to_sot/get_api_secret/trigger_glue_job mockados (nenhuma chamada real à
AWS/TMDB).

Foco: a orquestração do backfill — quais unidades são processadas, o contrato
"erro em uma unidade não aborta o backfill inteiro" (soft-fail-continue, mesmo padrão de
test/scripts/test_backfill_enriquecimento.py), o checkpoint, e o disparo único do Glue
Data Quality ao final cobrindo todo o range de anos. A lógica de coleta/transformação em
si é testada em test/lambda_api/test_utils.py e test/glue_etl/test_utils.py.
"""

import json
from unittest.mock import MagicMock, call, patch

import backfill_discover as bd
import pytest
from botocore.exceptions import ClientError

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "TABLE_GROUP": "discover",
    "S3_BUCKET_SOR": "bucket-sor-test",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "S3_BUCKET_TEMP": "bucket-temp-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_DISCOVER_MOVIE": "tb_discover_movie",
    "TABLE_DISCOVER_TV": "tb_discover_tv",
    "TMDB_SECRET_ARN": "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb",
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "S3_BUCKET_SPEC": "bucket-spec-test",
    "S3_PREFIX_SPEC": "tmdb",
    "DB_UNIFIED": "db_unified",
    "TABLE_DISCOVER_UNIFIED": "tb_discover_unified",
    "ENVIRONMENT": "dev",
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
    resultado: list | None = None,
    trigger_agg: bool = True,
    call_order: list | None = None,
):
    """Roda bd.main() com collect_discover_data/read_from_sor/write_parquet_to_sot mockados.

    unit_side_effect define o comportamento de collect_discover_data por unidade — lista de
    exceções/None (na ordem das unidades pendentes) ou uma função. Como collect_discover_data
    roda antes de read_from_sor/write_parquet_to_sot dentro do mesmo bloco try, uma falha ali
    já é suficiente para simular a falha da unidade inteira.

    resultado (se passado) recebe o retorno bool de bd.main() — parâmetro à parte para não mudar
    a tupla de mocks já retornada por esta função (consumida por *_ em quase todo teste existente).

    call_order (se passado) recebe, na ordem real de execução, "trigger_agg_locally" e
    "clear_checkpoint" — usado para travar que o AGG roda antes do checkpoint ser limpo (ver
    scripts/backfill_shared.py:trigger_agg_locally, decisão de design #1 do plano).
    """
    _set_env(monkeypatch, overrides)
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()
    if call_order is not None:
        mock_s3.delete_object.side_effect = lambda *a, **k: call_order.append("clear_checkpoint")

    with (
        patch("backfill_discover.boto3") as mock_boto3,
        patch("backfill_discover.time.sleep") as mock_sleep,
        patch("backfill_discover.get_api_secret", return_value="tmdb-key") as mock_secret,
        patch("backfill_discover.collect_discover_data") as mock_collect,
        patch("backfill_discover.read_from_sor", return_value="df-fake") as mock_read,
        patch("backfill_discover.write_parquet_to_sot") as mock_write,
        patch("backfill_discover.trigger_glue_job") as mock_trigger,
        patch("backfill_discover.shared.trigger_agg_locally") as mock_agg,
    ):
        mock_boto3.client.return_value = mock_s3
        if unit_side_effect is not None:
            mock_collect.side_effect = unit_side_effect
        if call_order is not None:
            mock_agg.side_effect = lambda *a, **k: call_order.append("trigger_agg_locally")
        sucesso = bd.main(trigger_agg=trigger_agg)
        if resultado is not None:
            resultado.append(sucesso)
    return mock_collect, mock_read, mock_write, mock_sleep, mock_s3, mock_secret, mock_trigger, mock_agg


class TestLoopPrincipal:
    def test_total_de_unidades_e_anos_vezes_dois_tipos(self, monkeypatch):
        mock_collect, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_collect.call_count == 6  # 3 anos x 2 tipos

    def test_intercala_movie_e_tv_por_ano(self, monkeypatch):
        mock_collect, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        media_types = [c.kwargs["content_type"] for c in mock_collect.call_args_list]
        assert media_types == ["movie", "tv", "movie", "tv"]

    def test_falha_em_uma_unidade_nao_interrompe_o_backfill(self, monkeypatch):
        mock_collect, *_ = _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"},
            unit_side_effect=[Exception("boom"), None, None, None],
        )
        assert mock_collect.call_count == 4

    def test_read_e_write_pulados_quando_a_coleta_falha(self, monkeypatch):
        mock_collect, mock_read, mock_write, *_ = _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
            unit_side_effect=[Exception("boom"), None],
        )
        assert mock_read.call_count == 1
        assert mock_write.call_count == 1

    def test_nao_pausa_apos_ultima_unidade(self, monkeypatch):
        mock_collect, _, _, mock_sleep, *_ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"},
        )
        # WAIT_SECONDS default (15) entre unidades, mais 2 sleeps do disparo final de DQ (um por tabela)
        assert mock_sleep.call_count == (mock_collect.call_count - 1) + 2

    def test_loga_resumo_das_falhas_ao_final(self, monkeypatch, caplog):
        with caplog.at_level("ERROR", logger="backfill_discover"):
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
        with caplog.at_level("ERROR", logger="backfill_discover"):
            _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        resumo = [r.message for r in caplog.records if "precisam ser re-executadas" in r.message]
        assert resumo == []

    def test_busca_api_key_uma_unica_vez_fora_do_loop(self, monkeypatch):
        _, _, _, _, _, mock_secret, _, _ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"},
        )
        mock_secret.assert_called_once_with(
            "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb", "tmdb_api_key",
        )

    def test_api_key_repassada_para_cada_unidade(self, monkeypatch):
        mock_collect, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for c in mock_collect.call_args_list:
            assert c.kwargs["api_key"] == "tmdb-key"


class TestPipelineDiscover:
    """Garante que collect_discover_data/read_from_sor/write_parquet_to_sot são chamados com
    os argumentos equivalentes ao que o Glue ETL/Lambda usariam para table_type='discover'."""

    def test_collect_discover_data_recebe_folder_e_bucket_corretos(self, monkeypatch):
        mock_collect, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        movie_call = mock_collect.call_args_list[0]
        assert movie_call.kwargs["bucket"] == "bucket-sor-test"
        assert movie_call.kwargs["folder"] == "tmdb/discover/movie"
        assert movie_call.kwargs["year"] == 2020

    def test_read_from_sor_recebe_table_type_discover(self, monkeypatch):
        _, mock_read, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for c in mock_read.call_args_list:
            assert c.args[2] == "discover"

    def test_write_parquet_particiona_por_ano_com_overwrite_partitions(self, monkeypatch):
        _, _, mock_write, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        for c in mock_write.call_args_list:
            assert c.kwargs["partition_cols"] == ["year"]
            assert c.kwargs["mode"] == "overwrite_partitions"

    def test_write_parquet_usa_tabela_e_database_do_media_type(self, monkeypatch):
        _, _, mock_write, *_ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        movie_call, tv_call = mock_write.call_args_list
        assert movie_call.kwargs["table_name"] == "tb_discover_movie"
        assert movie_call.kwargs["database"] == "db_movie"
        assert tv_call.kwargs["table_name"] == "tb_discover_tv"
        assert tv_call.kwargs["database"] == "db_tv"


class TestTranslateProviderGuard:
    def test_translate_provider_default_google_propagado(self, monkeypatch):
        with patch("backfill_discover.resolve_detect_language_fn") as mock_resolve:
            _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        assert mock_resolve.call_args.kwargs["provider"] == "google"

    def test_translate_provider_aws_propagado_para_intervalo_de_1_ano(self, monkeypatch):
        with patch("backfill_discover.resolve_detect_language_fn") as mock_resolve:
            _run_main(
                monkeypatch,
                {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020", "TRANSLATE_PROVIDER": "aws"},
            )
        assert mock_resolve.call_args.kwargs["provider"] == "aws"

    def test_translate_provider_aws_rebaixado_para_google_em_intervalo_maior_que_1_ano(self, monkeypatch):
        """Proteção de custo: aws só é aceito para um intervalo de 1 ano — ver
        backfill_shared.apply_translate_cost_guard."""
        with patch("backfill_discover.resolve_detect_language_fn") as mock_resolve:
            _run_main(
                monkeypatch,
                {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021", "TRANSLATE_PROVIDER": "aws"},
            )
        assert mock_resolve.call_args.kwargs["provider"] == "google"


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("TMDB_SECRET_ARN", raising=False)
        with pytest.raises(EnvironmentError):
            bd.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetSecretValue")
        assert bd.shared.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "GetSecretValue")
        assert bd.shared.expired_token_exit_code(exc) == 75

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_token_expirado_em_uma_unidade_propaga_sem_ser_capturado_como_falha_soft(self, monkeypatch, codigo):
        """Token expirado precisa propagar (para o run_with_retry_exit tratar como exit 75),
        não ser tratado como falha soft-fail-continue de uma unidade qualquer."""
        exc = ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "PutObject")
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

        mock_collect, *_ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"}, mock_s3=mock_s3,
        )

        pendentes = [(c.kwargs["content_type"], c.kwargs["year"]) for c in mock_collect.call_args_list]
        assert pendentes == [("tv", 2020), ("tv", 2021)]

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
        resultado: list = []

        _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
            mock_s3=mock_s3, resultado=resultado,
        )

        mock_s3.delete_object.assert_called_once()
        assert resultado == [True]

    def test_nao_limpa_checkpoint_quando_ha_falhas(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        resultado: list = []

        _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
            unit_side_effect=[Exception("falhou"), None],
            mock_s3=mock_s3,
            resultado=resultado,
        )

        mock_s3.delete_object.assert_not_called()
        assert resultado == [False]


class TestDataQualityFinal:
    def test_dispara_dq_uma_vez_por_tabela_cobrindo_o_range_completo(self, monkeypatch):
        *_, mock_trigger, mock_agg = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})

        assert mock_trigger.call_count == 2
        assert call("dq-job", TABLE_NAME="tb_discover_movie", DATABASE="db_movie", YEAR="2020,2021") in mock_trigger.call_args_list
        assert call("dq-job", TABLE_NAME="tb_discover_tv", DATABASE="db_tv", YEAR="2020,2021") in mock_trigger.call_args_list

    def test_nao_dispara_dq_quando_ha_falhas(self, monkeypatch):
        *_, mock_trigger, mock_agg = _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
            unit_side_effect=[Exception("falhou"), None],
        )
        mock_trigger.assert_not_called()


class TestGlueAgg:
    def test_chamado_uma_vez_quando_sem_falhas(self, monkeypatch):
        *_, mock_agg = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        mock_agg.assert_called_once_with(
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

    def test_nao_chamado_quando_ha_falhas(self, monkeypatch):
        *_, mock_agg = _run_main(
            monkeypatch,
            {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"},
            unit_side_effect=[Exception("falhou"), None],
        )
        mock_agg.assert_not_called()

    def test_nao_chamado_quando_trigger_agg_false(self, monkeypatch):
        *_, mock_agg = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, trigger_agg=False,
        )
        mock_agg.assert_not_called()

    def test_chamado_antes_de_clear_checkpoint(self, monkeypatch):
        call_order: list = []
        _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, call_order=call_order,
        )
        assert call_order == ["trigger_agg_locally", "clear_checkpoint"]
