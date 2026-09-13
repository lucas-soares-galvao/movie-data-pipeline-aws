"""
Testa scripts/backfill_changes.py com collect_changes_data/fetch_ids_from_changes_file/
process_changed_ids/get_api_secret/trigger_glue_job mockados (nenhuma chamada real à AWS/TMDB).

Foco: a orquestração do backfill (independente do Glue Details e da Lambda desde que o script
passou a rodar a coleta de changes + enriquecimento diretamente no processo — ver
app/glue_details/glue_details.md, seção "Reuso fora do Glue (backfill de changes)"): quais
content_types são processados, o contrato "erro em um content_type não aborta o outro"
(soft-fail-continue, mesmo padrão de backfill_enriquecimento.py) e o disparo único do Glue Data
Quality ao final por tabela, só se nada falhou. A lógica de negócio em si (collect_changes_data,
process_changed_ids) é testada em test/lambda_api/test_utils.py e test/glue_details/test_utils.py.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import backfill_changes as bc
import pytest
from botocore.exceptions import ClientError

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_DISCOVER_MOVIE": "tb_discover_movie",
    "TABLE_DISCOVER_TV": "tb_discover_tv",
    "TABLE_DETAILS_MOVIE": "tb_details_movie",
    "TABLE_DETAILS_TV": "tb_details_tv",
    "TABLE_WATCH_PROVIDERS_MOVIE": "tb_wp_movie",
    "TABLE_WATCH_PROVIDERS_TV": "tb_wp_tv",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "S3_BUCKET_TEMP": "bucket-temp-test",
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


def _window_key() -> int:
    """Mesma data de referência ("ontem", UTC) que backfill_changes.main() usa como chave de
    validação do checkpoint, no lugar de start_year/end_year."""
    return int((datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y%m%d"))


def _s3_client_sem_checkpoint() -> MagicMock:
    """Cliente S3 mockado simulando ausência de checkpoint (comportamento padrão nos testes)."""
    client = MagicMock()
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject",
    )
    return client


def _s3_client_com_checkpoint(completed: list) -> MagicMock:
    """Cliente S3 mockado retornando um checkpoint existente com as unidades já concluídas."""
    client = MagicMock()
    body = json.dumps(
        {"start_year": _window_key(), "end_year": _window_key(), "completed": completed}
    ).encode()
    client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=body))}
    return client


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict | None = None,
    process_side_effect=None,
    affected_years_by_type: dict | None = None,
    notify_capture: list | None = None,
    mock_s3: MagicMock | None = None,
):
    """Roda bc.main() com collect_changes_data/fetch_ids_from_changes_file/process_changed_ids/
    trigger_glue_job mockados.

    process_side_effect define o comportamento de process_changed_ids por content_type — lista de
    exceções/valores (na ordem dos content_types pendentes) ou uma função. affected_years_by_type
    sobrescreve o retorno padrão (lista vazia) por content_type quando process_side_effect não é
    informado.

    notify_capture (se passado) recebe o mock de shared.notify_backfill_success — não muda a
    tupla de mocks já retornada por esta função (consumida por unpacking fixo em alguns testes).

    mock_s3 (se passado) substitui o cliente S3 padrão (sem checkpoint — ver
    _s3_client_sem_checkpoint) — usado pelos testes de checkpoint para simular um checkpoint
    pré-existente (ver _s3_client_com_checkpoint) ou para inspecionar put_object/delete_object.
    """
    _set_env(monkeypatch, overrides)
    affected_years_by_type = affected_years_by_type or {}
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()

    def _default_process(*, content_type, **_kwargs):
        return affected_years_by_type.get(content_type, [])

    with (
        patch("backfill_changes.boto3") as mock_boto3,
        patch("backfill_changes.get_api_secret", return_value="tmdb-key") as mock_secret,
        patch("backfill_changes.collect_changes_data") as mock_collect,
        patch("backfill_changes.fetch_ids_from_changes_file") as mock_fetch,
        patch("backfill_changes.process_changed_ids") as mock_process,
        patch("backfill_changes.trigger_glue_job") as mock_trigger,
        patch("backfill_changes.shared.trigger_agg_locally") as mock_agg,
        patch("backfill_changes.shared.notify_backfill_success") as mock_notify,
    ):
        mock_boto3.client.return_value = mock_s3
        mock_collect.side_effect = lambda api_key, s3_client, bucket, content_type: f"tmdb/changes/{content_type}/2026-01-01.json"
        mock_fetch.return_value = {"ids": [1, 2, 3], "start_date": "2025-12-25", "end_date": "2026-01-01"}
        if process_side_effect is not None:
            mock_process.side_effect = process_side_effect
        else:
            mock_process.side_effect = _default_process
        bc.main()
        if notify_capture is not None:
            notify_capture.append(mock_notify)
    return mock_collect, mock_fetch, mock_process, mock_trigger, mock_secret, mock_agg


class TestLoopPrincipal:
    def test_processa_movie_e_tv(self, monkeypatch):
        mock_collect, *_ = _run_main(monkeypatch)
        content_types = [c.args[3] for c in mock_collect.call_args_list]
        assert content_types == ["movie", "tv"]

    def test_database_correto_por_content_type(self, monkeypatch):
        _, _, mock_process, *_ = _run_main(monkeypatch)
        por_tipo = {c.kwargs["content_type"]: c.kwargs["database"] for c in mock_process.call_args_list}
        assert por_tipo == {"movie": "db_movie", "tv": "db_tv"}

    def test_tabelas_corretas_por_content_type(self, monkeypatch):
        _, _, mock_process, *_ = _run_main(monkeypatch)
        chamada_movie = next(c for c in mock_process.call_args_list if c.kwargs["content_type"] == "movie")
        chamada_tv = next(c for c in mock_process.call_args_list if c.kwargs["content_type"] == "tv")
        assert chamada_movie.kwargs["table_discover"] == "tb_discover_movie"
        assert chamada_movie.kwargs["table_details"] == "tb_details_movie"
        assert chamada_movie.kwargs["table_watch_providers"] == "tb_wp_movie"
        assert chamada_tv.kwargs["table_discover"] == "tb_discover_tv"
        assert chamada_tv.kwargs["table_details"] == "tb_details_tv"
        assert chamada_tv.kwargs["table_watch_providers"] == "tb_wp_tv"

    def test_fetch_ids_usa_s3_path_retornado_por_collect(self, monkeypatch):
        _, mock_fetch, *_ = _run_main(monkeypatch)
        caminhos = [c.args[0] for c in mock_fetch.call_args_list]
        assert caminhos == [
            "s3://bucket-temp-test/tmdb/changes/movie/2026-01-01.json",
            "s3://bucket-temp-test/tmdb/changes/tv/2026-01-01.json",
        ]

    def test_changed_ids_repassados_para_process_changed_ids(self, monkeypatch):
        _, _, mock_process, *_ = _run_main(monkeypatch)
        for c in mock_process.call_args_list:
            assert c.kwargs["changed_ids"] == [1, 2, 3]

    def test_falha_em_um_content_type_nao_impede_o_outro(self, monkeypatch):
        """Mesmo padrão soft-fail-continue de backfill_discover.py/backfill_enriquecimento.py:
        uma exceção aqui só é logada, não aborta o loop."""
        _, _, mock_process, *_ = _run_main(monkeypatch, process_side_effect=[Exception("boom"), []])
        assert mock_process.call_count == 2

    def test_busca_api_key_uma_unica_vez_fora_do_loop(self, monkeypatch):
        *_, mock_secret, _ = _run_main(monkeypatch)
        mock_secret.assert_called_once_with(
            "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb", "tmdb_api_key"
        )

    def test_api_key_repassada_para_cada_content_type(self, monkeypatch):
        _, _, mock_process, *_ = _run_main(monkeypatch)
        for c in mock_process.call_args_list:
            assert c.kwargs["api_key"] == "tmdb-key"

    def test_translate_provider_default_google(self, monkeypatch):
        _, _, mock_process, *_ = _run_main(monkeypatch)
        for c in mock_process.call_args_list:
            assert c.kwargs["translate_provider"] == "google"

    def test_translate_provider_repassado_quando_informado(self, monkeypatch):
        _, _, mock_process, *_ = _run_main(monkeypatch, {"TRANSLATE_PROVIDER": "aws"})
        for c in mock_process.call_args_list:
            assert c.kwargs["translate_provider"] == "aws"


class TestDataQualityFinal:
    def test_dispara_dq_uma_vez_por_tabela_cobrindo_todos_os_anos_afetados(self, monkeypatch):
        _, _, _, mock_trigger, _, _ = _run_main(
            monkeypatch,
            affected_years_by_type={"movie": ["2020", "2021"], "tv": ["2023"]},
        )
        assert mock_trigger.call_count == 4
        assert call("dq-job", TABLE_NAME="tb_details_movie", DATABASE="db_movie", YEAR="2020,2021") in mock_trigger.call_args_list
        assert call("dq-job", TABLE_NAME="tb_wp_movie", DATABASE="db_movie", YEAR="2020,2021") in mock_trigger.call_args_list
        assert call("dq-job", TABLE_NAME="tb_details_tv", DATABASE="db_tv", YEAR="2023") in mock_trigger.call_args_list
        assert call("dq-job", TABLE_NAME="tb_wp_tv", DATABASE="db_tv", YEAR="2023") in mock_trigger.call_args_list

    def test_nao_dispara_dq_para_tabela_sem_anos_afetados(self, monkeypatch):
        _, _, _, mock_trigger, _, _ = _run_main(
            monkeypatch, affected_years_by_type={"movie": [], "tv": ["2023"]},
        )
        assert mock_trigger.call_count == 2
        tabelas_disparadas = {c.kwargs["TABLE_NAME"] for c in mock_trigger.call_args_list}
        assert tabelas_disparadas == {"tb_details_tv", "tb_wp_tv"}

    def test_nao_dispara_dq_quando_ha_falhas(self, monkeypatch):
        _, _, _, mock_trigger, _, _ = _run_main(
            monkeypatch, process_side_effect=[Exception("falhou"), []],
        )
        mock_trigger.assert_not_called()


class TestGlueAgg:
    def test_chamado_uma_vez_quando_sem_falhas(self, monkeypatch):
        *_, mock_agg = _run_main(monkeypatch)
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
        *_, mock_agg = _run_main(monkeypatch, process_side_effect=[Exception("falhou"), []])
        mock_agg.assert_not_called()


class TestNotificacaoSucesso:
    def test_chamado_quando_nao_ha_falhas(self, monkeypatch):
        notify_capture: list = []
        _run_main(monkeypatch, notify_capture=notify_capture)
        mock_notify = notify_capture[0]
        mock_notify.assert_called_once_with(
            "changes", "Changes disparado com sucesso para movie e tv, Data Quality e Glue AGG disparados.",
        )

    def test_nao_chamado_quando_ha_falhas(self, monkeypatch):
        notify_capture: list = []
        _run_main(monkeypatch, process_side_effect=[Exception("falhou"), []], notify_capture=notify_capture)
        mock_notify = notify_capture[0]
        mock_notify.assert_not_called()


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("TMDB_SECRET_ARN", raising=False)
        with pytest.raises(EnvironmentError):
            bc.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetSecretValue")
        assert bc.shared.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "GetSecretValue")
        assert bc.shared.expired_token_exit_code(exc) == 75

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_token_expirado_em_um_content_type_propaga_sem_ser_capturado_como_falha_soft(
        self, monkeypatch, codigo,
    ):
        """Token expirado precisa propagar (para o run_with_retry_exit tratar como exit 75),
        não ser tratado como falha soft-fail-continue de um content_type qualquer."""
        exc = ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "StartQueryExecution")
        with pytest.raises(ClientError):
            _run_main(monkeypatch, process_side_effect=[exc])


class TestCheckpoint:
    def test_pula_content_type_ja_concluido(self, monkeypatch):
        mock_s3 = _s3_client_com_checkpoint(["movie|2020,2021"])
        _, _, mock_process, *_ = _run_main(monkeypatch, mock_s3=mock_s3)
        tipos_processados = [c.kwargs["content_type"] for c in mock_process.call_args_list]
        assert tipos_processados == ["tv"]

    def test_salva_checkpoint_apenas_para_content_type_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, process_side_effect=[Exception("falhou"), []], mock_s3=mock_s3)
        assert mock_s3.put_object.call_count == 1
        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["tv|"]

    def test_limpa_checkpoint_ao_concluir_tudo_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, mock_s3=mock_s3)
        mock_s3.delete_object.assert_called_once()

    def test_nao_limpa_checkpoint_quando_ha_falha(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, process_side_effect=[Exception("falhou"), []], mock_s3=mock_s3)
        mock_s3.delete_object.assert_not_called()

    def test_dq_disparado_com_anos_do_content_type_retomado_do_checkpoint(self, monkeypatch):
        """O content_type retomado do checkpoint (não reprocessado nesta execução) precisa
        continuar disparando o Data Quality com os affected_years persistidos junto dele."""
        mock_s3 = _s3_client_com_checkpoint(["movie|2020"])
        _, _, mock_process, mock_trigger, *_ = _run_main(
            monkeypatch, mock_s3=mock_s3, affected_years_by_type={"tv": ["2023"]},
        )
        assert [c.kwargs["content_type"] for c in mock_process.call_args_list] == ["tv"]
        chamadas_movie = [c for c in mock_trigger.call_args_list if c.kwargs["DATABASE"] == "db_movie"]
        assert len(chamadas_movie) == 2
        assert all(c.kwargs["YEAR"] == "2020" for c in chamadas_movie)
