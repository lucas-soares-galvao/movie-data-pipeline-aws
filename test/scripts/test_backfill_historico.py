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
from unittest.mock import MagicMock, patch

import backfill_historico as bh
import pytest
from botocore.exceptions import ClientError

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "S3_BUCKET_TEMP": "bucket-temp-test",
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


def _s3_client_com_checkpoint(stages: list[str]) -> MagicMock:
    client = MagicMock()
    client.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=json.dumps(
            {"start_year": 2020, "end_year": 2021, "completed": stages}
        ).encode()))
    }
    return client


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict | None = None,
    discover_result: bool = True,
    enriquecimento_result: bool = True,
    discover_side_effect=None,
    mock_s3: MagicMock | None = None,
):
    """Roda bh.main() com backfill_discover.main/backfill_enriquecimento.main mockados.

    discover_side_effect (se definido) tem prioridade sobre discover_result — usado para simular
    uma exceção (ex.: token expirado) em vez de um retorno bool.
    """
    _set_env(monkeypatch, overrides)
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()

    table_groups_no_momento_da_chamada: list[str | None] = []

    def _discover_main(trigger_agg: bool = True):
        table_groups_no_momento_da_chamada.append(os.environ.get("TABLE_GROUP"))
        if discover_side_effect is not None:
            raise discover_side_effect
        return discover_result

    def _enriquecimento_main(trigger_agg: bool = True):
        table_groups_no_momento_da_chamada.append(os.environ.get("TABLE_GROUP"))
        return enriquecimento_result

    with (
        patch("backfill_historico.boto3") as mock_boto3,
        patch("backfill_historico.backfill_discover") as mock_discover,
        patch("backfill_historico.backfill_enriquecimento") as mock_enriquecimento,
        patch("backfill_historico.shared.trigger_agg_locally") as mock_agg,
        patch("backfill_historico.shared.notify_backfill_success") as mock_notify,
    ):
        mock_boto3.client.return_value = mock_s3
        mock_discover.main.side_effect = _discover_main
        mock_enriquecimento.main.side_effect = _enriquecimento_main
        bh.main()
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
