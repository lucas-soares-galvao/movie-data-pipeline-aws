"""
Testa scripts/backfill_historico.py com backfill_discover.main/backfill_enriquecimento.main
mockados (nenhuma chamada real à AWS/TMDB, nem execução da lógica interna dos dois scripts — essa
lógica já é testada em test_backfill_discover.py/test_backfill_enriquecimento.py).

Foco: a orquestração entre os dois estágios — ordem, TABLE_GROUP definido antes de cada chamada,
interrupção quando um estágio termina com falhas pendentes (retorno False), e o checkpoint de
estágio próprio (unidade = nome do estágio, diferente do checkpoint por ano/tipo de cada script
encadeado).
"""

import json
import os
from unittest.mock import MagicMock, call, patch

import backfill_historico as bh
import pytest
from botocore.exceptions import ClientError

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "S3_BUCKET_TEMP": "bucket-temp-test",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "TABLE_DISCOVER_MOVIE": "tb_discover_movie",
    "TABLE_DISCOVER_TV": "tb_discover_tv",
    "TABLE_DETAILS_MOVIE": "tb_details_movie",
    "TABLE_DETAILS_TV": "tb_details_tv",
    "TABLE_WATCH_PROVIDERS_MOVIE": "tb_wp_movie",
    "TABLE_WATCH_PROVIDERS_TV": "tb_wp_tv",
    "BACKFILL_START_YEAR": "2020",
    "BACKFILL_END_YEAR": "2021",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
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


def _s3_client_com_checkpoint(stages: list[str], mode: str | None = None) -> MagicMock:
    client = MagicMock()
    payload = {"start_year": 2020, "end_year": 2021, "completed": stages}
    if mode:
        payload["mode"] = mode
    client.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=json.dumps(payload).encode()))
    }
    return client


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict | None = None,
    discover_result: bool = True,
    enriquecimento_result: bool = True,
    discover_side_effect=None,
    mock_s3: MagicMock | None = None,
    discover_ids=None,
    prune_side_effect=None,
    capture: dict | None = None,
):
    """Roda bh.main() com backfill_discover.main/backfill_enriquecimento.main mockados.

    discover_side_effect (se definido) tem prioridade sobre discover_result — usado para simular
    uma exceção (ex.: token expirado) em vez de um retorno bool.

    discover_ids é o conjunto devolvido por fetch_all_discover_ids (padrão {1, 2}); prune_side_effect
    (se definido) é o side_effect de prune_table_to_ids. capture (se passado) recebe as chaves
    "fetch" e "prune" (mocks) e "ordem" (lista com a ordem real dos estágios) — parâmetro à parte
    para não mudar a tupla de retorno consumida por *_ nos testes existentes.
    """
    monkeypatch.delenv("BACKFILL_REPROCESS_ALL", raising=False)
    _set_env(monkeypatch, overrides)
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()

    table_groups_no_momento_da_chamada: list[str | None] = []

    ordem: list[str] = []

    def _discover_main(trigger_agg: bool = True):
        ordem.append("discover")
        table_groups_no_momento_da_chamada.append(os.environ.get("TABLE_GROUP"))
        if discover_side_effect is not None:
            raise discover_side_effect
        return discover_result

    def _enriquecimento_main(trigger_agg: bool = True):
        ordem.append("enriquecimento")
        table_groups_no_momento_da_chamada.append(os.environ.get("TABLE_GROUP"))
        return enriquecimento_result

    def _prune(*args, **kwargs):
        ordem.append("poda")
        return 3

    with (
        patch("backfill_historico.boto3") as mock_boto3,
        patch("backfill_historico.backfill_discover") as mock_discover,
        patch("backfill_historico.backfill_enriquecimento") as mock_enriquecimento,
        patch("backfill_historico.shared.trigger_agg_locally") as mock_agg,
        patch("backfill_historico.shared.notify_backfill_success") as mock_notify,
        patch(
            "backfill_historico.fetch_all_discover_ids",
            return_value={1, 2} if discover_ids is None else discover_ids,
        ) as mock_fetch,
        patch("backfill_historico.prune_table_to_ids") as mock_prune,
    ):
        mock_boto3.client.return_value = mock_s3
        mock_discover.main.side_effect = _discover_main
        mock_enriquecimento.main.side_effect = _enriquecimento_main
        mock_prune.side_effect = prune_side_effect or _prune
        try:
            bh.main()
        finally:
            if capture is not None:
                capture.update(fetch=mock_fetch, prune=mock_prune, ordem=ordem)
    return mock_discover, mock_enriquecimento, mock_s3, table_groups_no_momento_da_chamada, mock_agg, mock_notify


class TestOrdemDosEstagios:
    def test_roda_discover_e_depois_enriquecimento(self, monkeypatch):
        mock_discover, mock_enriquecimento, *_ = _run_main(monkeypatch)
        mock_discover.main.assert_called_once()
        mock_enriquecimento.main.assert_called_once()

    def test_define_table_group_de_cada_estagio_antes_de_chamar(self, monkeypatch):
        *_, table_groups, _, _ = _run_main(monkeypatch)
        assert table_groups == ["discover", "detalhes_e_providers"]


class TestInterrupcaoPorFalha:
    def test_nao_chama_enriquecimento_quando_discover_retorna_false(self, monkeypatch):
        mock_discover, mock_enriquecimento, *_ = _run_main(monkeypatch, discover_result=False)
        mock_discover.main.assert_called_once()
        mock_enriquecimento.main.assert_not_called()

    def test_nao_salva_estagio_discover_no_checkpoint_quando_retorna_false(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, discover_result=False, mock_s3=mock_s3)
        mock_s3.put_object.assert_not_called()

    def test_salva_discover_mas_nao_limpa_checkpoint_quando_enriquecimento_retorna_false(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, enriquecimento_result=False, mock_s3=mock_s3)

        assert mock_s3.put_object.call_count == 1
        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["discover"]
        mock_s3.delete_object.assert_not_called()


class TestSucessoCompleto:
    def test_salva_os_dois_estagios_e_limpa_checkpoint_ao_final(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, mock_s3=mock_s3)

        assert mock_s3.put_object.call_count == 2
        segundo_save = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert sorted(segundo_save["completed"]) == ["discover", "enriquecimento"]
        mock_s3.delete_object.assert_called_once()

    def test_loga_conclusao_quando_tudo_sucede(self, monkeypatch, caplog):
        with caplog.at_level("INFO", logger="backfill_historico"):
            _run_main(monkeypatch)
        resumo = [r.message for r in caplog.records if "Backfill histórico concluído" in r.message]
        assert len(resumo) == 1


class TestPodaDeOrfaos:
    """Estágio "poda" do "Reprocessar tudo": só com a flag, entre discover e enriquecimento."""

    _FLAG = {"BACKFILL_REPROCESS_ALL": "true"}

    def test_sem_a_flag_nao_poda(self, monkeypatch):
        capturado: dict = {}
        _run_main(monkeypatch, capture=capturado)

        capturado["fetch"].assert_not_called()
        capturado["prune"].assert_not_called()
        assert capturado["ordem"] == ["discover", "enriquecimento"]

    def test_com_a_flag_poda_entre_discover_e_enriquecimento(self, monkeypatch):
        capturado: dict = {}
        _run_main(monkeypatch, self._FLAG, capture=capturado)

        assert capturado["ordem"] == ["discover", "poda", "poda", "poda", "poda", "enriquecimento"]

    def test_poda_as_quatro_tabelas_contra_o_discover_de_todos_os_anos_do_range(self, monkeypatch):
        capturado: dict = {}
        _run_main(monkeypatch, self._FLAG, discover_ids={7, 8}, capture=capturado)

        assert capturado["fetch"].call_args_list == [
            call("db_movie", "tb_discover_movie", "bucket-temp-test"),
            call("db_tv", "tb_discover_tv", "bucket-temp-test"),
        ]
        anos = {"2020", "2021"}
        assert capturado["prune"].call_args_list == [
            call("bucket-sot-test", "tb_details_movie", "db_movie", {7, 8}, anos),
            call("bucket-sot-test", "tb_wp_movie", "db_movie", {7, 8}, anos),
            call("bucket-sot-test", "tb_details_tv", "db_tv", {7, 8}, anos),
            call("bucket-sot-test", "tb_wp_tv", "db_tv", {7, 8}, anos),
        ]

    def test_registra_o_estagio_poda_no_checkpoint(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, self._FLAG, mock_s3=mock_s3)

        saves = [json.loads(c.kwargs["Body"]) for c in mock_s3.put_object.call_args_list]
        assert [sorted(x["completed"]) for x in saves] == [
            ["discover"], ["discover", "poda"], ["discover", "enriquecimento", "poda"],
        ]
        assert all(x["mode"] == "reprocess_all" for x in saves)

    def test_pula_a_poda_quando_o_checkpoint_do_mesmo_modo_ja_a_tem(self, monkeypatch):
        mock_s3 = _s3_client_com_checkpoint(["discover", "poda"], mode="reprocess_all")
        capturado: dict = {}
        mock_discover, mock_enriquecimento, *_ = _run_main(
            monkeypatch, self._FLAG, mock_s3=mock_s3, capture=capturado,
        )

        mock_discover.main.assert_not_called()
        capturado["prune"].assert_not_called()
        mock_enriquecimento.main.assert_called_once()

    def test_checkpoint_de_run_normal_e_ignorado_e_a_poda_roda(self, monkeypatch):
        mock_s3 = _s3_client_com_checkpoint(["discover", "enriquecimento"])
        capturado: dict = {}
        mock_discover, *_ = _run_main(monkeypatch, self._FLAG, mock_s3=mock_s3, capture=capturado)

        mock_discover.main.assert_called_once()
        assert capturado["prune"].call_count == 4

    def test_nao_poda_quando_o_discover_falhou(self, monkeypatch):
        capturado: dict = {}
        _run_main(monkeypatch, self._FLAG, discover_result=False, capture=capturado)

        capturado["fetch"].assert_not_called()
        capturado["prune"].assert_not_called()

    def test_discover_vazio_aborta_sem_podar_nem_enriquecer(self, monkeypatch, caplog):
        capturado: dict = {}
        mock_s3 = _s3_client_sem_checkpoint()
        with caplog.at_level("ERROR", logger="backfill_historico"):
            _, mock_enriquecimento, *_ = _run_main(
                monkeypatch, self._FLAG, discover_ids=set(), mock_s3=mock_s3, capture=capturado,
            )

        capturado["prune"].assert_not_called()
        mock_enriquecimento.main.assert_not_called()
        assert any("não tem nenhum id" in r.message for r in caplog.records)
        assert any("não concluído" in r.message for r in caplog.records)
        # só o estágio discover foi salvo; a poda não entrou no checkpoint
        assert json.loads(mock_s3.put_object.call_args.kwargs["Body"])["completed"] == ["discover"]
        mock_s3.delete_object.assert_not_called()

    def test_erro_na_poda_interrompe_o_historico(self, monkeypatch):
        *resto, mock_agg, mock_notify = _run_main(
            monkeypatch, self._FLAG, prune_side_effect=RuntimeError("boom"),
        )
        mock_enriquecimento = resto[1]

        mock_enriquecimento.main.assert_not_called()
        mock_agg.assert_not_called()
        mock_notify.assert_not_called()

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_token_expirado_na_poda_propaga_para_o_exit_75(self, monkeypatch, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "GetObject")
        with pytest.raises(ClientError):
            _run_main(monkeypatch, self._FLAG, prune_side_effect=exc)

    def test_outro_client_error_na_poda_interrompe_sem_propagar(self, monkeypatch):
        exc = ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "GetObject")
        _, mock_enriquecimento, *_ = _run_main(monkeypatch, self._FLAG, prune_side_effect=exc)

        mock_enriquecimento.main.assert_not_called()


class TestCheckpointDeEstagio:
    def test_pula_discover_quando_ja_concluido_no_checkpoint(self, monkeypatch):
        mock_s3 = _s3_client_com_checkpoint(["discover"])
        mock_discover, mock_enriquecimento, *_ = _run_main(monkeypatch, mock_s3=mock_s3)

        mock_discover.main.assert_not_called()
        mock_enriquecimento.main.assert_called_once()

    def test_pula_ambos_quando_checkpoint_ja_tem_os_dois_estagios(self, monkeypatch):
        mock_s3 = _s3_client_com_checkpoint(["discover", "enriquecimento"])
        mock_discover, mock_enriquecimento, *_ = _run_main(monkeypatch, mock_s3=mock_s3)

        mock_discover.main.assert_not_called()
        mock_enriquecimento.main.assert_not_called()
        mock_s3.delete_object.assert_called_once()


class TestGlueAgg:
    def test_estagios_chamados_com_trigger_agg_false(self, monkeypatch):
        mock_discover, mock_enriquecimento, *_ = _run_main(monkeypatch)
        mock_discover.main.assert_called_once_with(trigger_agg=False)
        mock_enriquecimento.main.assert_called_once_with(trigger_agg=False)

    def test_chamado_exatamente_uma_vez_quando_ambos_estagios_sucedem(self, monkeypatch):
        *_, mock_agg, _ = _run_main(monkeypatch)
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

    def test_nao_chamado_quando_discover_retorna_false(self, monkeypatch):
        *_, mock_agg, _ = _run_main(monkeypatch, discover_result=False)
        mock_agg.assert_not_called()

    def test_nao_chamado_quando_enriquecimento_retorna_false(self, monkeypatch):
        *_, mock_agg, _ = _run_main(monkeypatch, enriquecimento_result=False)
        mock_agg.assert_not_called()

    def test_chamado_uma_unica_vez_mesmo_quando_ambos_estagios_ja_estavam_no_checkpoint(self, monkeypatch):
        """Retomada: os dois estágios são pulados (já concluídos), mas o AGG ainda deve
        rodar (ainda não tinha sido disparado se a interrupção anterior ocorreu antes dele)."""
        mock_s3 = _s3_client_com_checkpoint(["discover", "enriquecimento"])
        *_, mock_agg, _ = _run_main(monkeypatch, mock_s3=mock_s3)
        mock_agg.assert_called_once()


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("S3_BUCKET_TEMP", raising=False)
        with pytest.raises(EnvironmentError):
            bh.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetSecretValue")
        assert bh.shared.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "GetSecretValue")
        assert bh.shared.expired_token_exit_code(exc) == 75

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_token_expirado_no_estagio_discover_propaga_e_nao_chama_enriquecimento(self, monkeypatch, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "GetObject")
        with pytest.raises(ClientError):
            _run_main(monkeypatch, discover_side_effect=exc)


class TestNotificacaoSucesso:
    def test_chamado_uma_vez_quando_ambos_estagios_sucedem(self, monkeypatch):
        *_, mock_notify = _run_main(monkeypatch)
        mock_notify.assert_called_once_with(
            "historico", "Backfill histórico concluído: discover + enriquecimento, sem pendências.",
        )

    def test_nao_chamado_quando_discover_retorna_false(self, monkeypatch):
        *_, mock_notify = _run_main(monkeypatch, discover_result=False)
        mock_notify.assert_not_called()

    def test_nao_chamado_quando_enriquecimento_retorna_false(self, monkeypatch):
        *_, mock_notify = _run_main(monkeypatch, enriquecimento_result=False)
        mock_notify.assert_not_called()
