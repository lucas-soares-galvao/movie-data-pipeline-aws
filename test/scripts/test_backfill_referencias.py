"""
Testa scripts/backfill_referencias.py com collect_genre_data/collect_configuration_data/
collect_watch_providers_ref/read_from_sor/write_parquet_to_sot/trigger_glue_job/get_api_secret
e load/save/clear_checkpoint mockados (nenhuma chamada real à AWS/TMDB).

Foco: a orquestração do backfill (independente da Lambda e do Glue ETL desde que o script passou
a rodar a coleta + transformação diretamente no processo — ver
app/lambda_api/lambda_api.md, seção "Backfill manual"): quais tabelas são processadas por
content_type, o contrato "erro em genre/configuration aborta, HTTPError em watch_providers_ref
não aborta", o disparo do Glue Data Quality uma vez por tabela gravada e o checkpoint por unidade
"{media_type}:{table_type}" que permite retomar depois de um token AWS expirado (exit code 75). A
lógica de negócio em si (collect_genre_data, read_from_sor, write_parquet_to_sot) é testada em
test/lambda_api/test_utils.py e test/glue_etl/test_utils.py; load/save/clear_checkpoint, em
test/scripts/test_backfill_shared.py.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import backfill_referencias as br
import pytest
from botocore.exceptions import ClientError
from requests.exceptions import HTTPError

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "S3_BUCKET_SOR": "bucket-sor-test",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "S3_BUCKET_TEMP": "bucket-temp-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_GENRE_MOVIE": "tb_genre_movie",
    "TABLE_GENRE_TV": "tb_genre_tv",
    "TABLE_CONFIGURATION_LANGUAGES": "tb_config_languages",
    "TABLE_CONFIGURATION_COUNTRIES": "tb_config_countries",
    "TABLE_WATCH_PROVIDERS_REF_MOVIE": "tb_wp_ref_movie",
    "TABLE_WATCH_PROVIDERS_REF_TV": "tb_wp_ref_tv",
    "TMDB_SECRET_ARN": "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb",
    "GLUE_DATA_QUALITY_JOB_NAME": "dq-job",
    "S3_BUCKET_SPEC": "bucket-spec-test",
    "S3_PREFIX_SPEC": "tmdb",
    "DB_UNIFIED": "db_unified",
    "TABLE_DISCOVER_UNIFIED": "tb_discover_unified",
    "ENVIRONMENT": "dev",
}

TODAS_AS_UNIDADES = {
    "movie:genre", "movie:configuration", "movie:watch_providers_ref",
    "tv:genre", "tv:configuration", "tv:watch_providers_ref",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> None:
    for key, value in {**ENV_BASE, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


def _token_expirado() -> ClientError:
    return ClientError({"Error": {"Code": "ExpiredToken", "Message": "x"}}, "PutObject")


@contextmanager
def _patched_main(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict | None = None,
    *,
    completed: set[str] | None = None,
    genre_side_effect=None,
    config_side_effect=None,
    wp_side_effect=None,
    write_side_effect=None,
):
    """Patcha tudo que br.main() toca fora do próprio script (TMDB, SOR/SOT, Glue, AWS e o
    checkpoint em S3) e devolve os mocks para inspeção — inclusive quando br.main() levanta
    exceção dentro do `with`. `completed` é o conteúdo que load_checkpoint devolve."""
    _set_env(monkeypatch, overrides)
    # Instantâneos do que foi passado a save_checkpoint: o mesmo set é mutado a cada unidade,
    # então call_args_list sozinho só mostraria o estado final em todas as chamadas.
    saved: list[set[str]] = []

    with (
        patch("backfill_referencias.boto3") as mock_boto3,
        patch("backfill_referencias.get_api_secret", return_value="tmdb-key") as mock_secret,
        patch("backfill_referencias.collect_genre_data", side_effect=genre_side_effect) as mock_genre,
        patch("backfill_referencias.collect_configuration_data", side_effect=config_side_effect) as mock_config,
        patch("backfill_referencias.collect_watch_providers_ref", side_effect=wp_side_effect) as mock_wp,
        patch("backfill_referencias.read_from_sor", return_value="df-fake") as mock_read,
        patch("backfill_referencias.write_parquet_to_sot", side_effect=write_side_effect) as mock_write,
        patch("backfill_referencias.trigger_glue_job") as mock_trigger,
        patch("backfill_referencias.shared.trigger_agg_locally") as mock_agg,
        patch("backfill_referencias.shared.notify_backfill_success") as mock_notify,
        patch("backfill_referencias.shared.load_checkpoint", return_value=set(completed or ())) as mock_load,
        patch(
            "backfill_referencias.shared.save_checkpoint",
            side_effect=lambda *args: saved.append(set(args[5])),
        ) as mock_save,
        patch("backfill_referencias.shared.clear_checkpoint") as mock_clear,
    ):
        s3_client = MagicMock()
        mock_boto3.client.return_value = s3_client
        yield {
            "s3_client": s3_client,
            "secret": mock_secret,
            "genre": mock_genre,
            "config": mock_config,
            "wp": mock_wp,
            "read": mock_read,
            "write": mock_write,
            "trigger": mock_trigger,
            "agg": mock_agg,
            "notify": mock_notify,
            "load": mock_load,
            "save": mock_save,
            "saved": saved,
            "clear": mock_clear,
        }


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict | None = None,
    collect_watch_providers_side_effect=None,
    completed: set[str] | None = None,
):
    """Roda br.main() até o fim (sem exceção) com tudo mockado e devolve os mocks."""
    with _patched_main(
        monkeypatch,
        overrides,
        completed=completed,
        wp_side_effect=collect_watch_providers_side_effect,
    ) as mocks:
        br.main()
    return mocks


class TestColetaPorContentType:
    def test_coleta_genre_configuration_watch_providers_para_movie_e_tv(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        assert [c.args[3] for c in mocks["genre"].call_args_list] == ["movie", "tv"]
        assert [c.args[3] for c in mocks["config"].call_args_list] == ["movie", "tv"]
        assert [c.args[3] for c in mocks["wp"].call_args_list] == ["movie", "tv"]

    def test_busca_api_key_uma_unica_vez_fora_do_loop(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        mocks["secret"].assert_called_once_with(
            "arn:aws:secretsmanager:sa-east-1:123456789:secret:tmdb", "tmdb_api_key"
        )

    def test_api_key_repassada_para_cada_coleta(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        for mock_fn in (mocks["genre"], mocks["config"], mocks["wp"]):
            for c in mock_fn.call_args_list:
                assert c.args[0] == "tmdb-key"


class TestEscritaNoSot:
    def test_grava_as_6_tabelas(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        tabelas_escritas = [c.kwargs["table_name"] for c in mocks["write"].call_args_list]
        assert sorted(tabelas_escritas) == sorted([
            "tb_genre_movie", "tb_genre_tv",
            "tb_config_languages", "tb_config_countries",
            "tb_wp_ref_movie", "tb_wp_ref_tv",
        ])

    def test_database_correto_por_content_type(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        por_tabela = {c.kwargs["table_name"]: c.kwargs["database"] for c in mocks["write"].call_args_list}
        assert por_tabela["tb_genre_movie"] == "db_movie"
        assert por_tabela["tb_genre_tv"] == "db_tv"
        assert por_tabela["tb_wp_ref_movie"] == "db_movie"
        assert por_tabela["tb_wp_ref_tv"] == "db_tv"

    def test_nenhuma_tabela_e_particionada(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        for c in mocks["write"].call_args_list:
            assert c.kwargs["partition_cols"] is None
            assert c.kwargs["mode"] == "overwrite"

    def test_read_from_sor_recebe_table_type_correto_por_tabela(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        chamadas = [(c.args[1], c.args[2]) for c in mocks["read"].call_args_list]
        assert ("movie", "genre") in chamadas
        assert ("tv", "genre") in chamadas
        assert ("movie", "configuration") in chamadas
        assert ("tv", "configuration") in chamadas
        assert ("movie", "watch_providers_ref") in chamadas
        assert ("tv", "watch_providers_ref") in chamadas


class TestDataQuality:
    def test_dispara_dq_uma_vez_por_tabela_gravada(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        assert mocks["trigger"].call_count == 6
        assert call("dq-job", TABLE_NAME="tb_genre_movie", DATABASE="db_movie") in mocks["trigger"].call_args_list
        assert call("dq-job", TABLE_NAME="tb_wp_ref_tv", DATABASE="db_tv") in mocks["trigger"].call_args_list


class TestGlueAgg:
    def test_chamado_uma_vez_ao_final(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        mocks["agg"].assert_called_once_with(
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


class TestNotificacaoSucesso:
    def test_chamado_ao_final_de_um_main_bem_sucedido(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        mocks["notify"].assert_called_once_with(
            "referencias",
            "Backfill de referências concluído: genre, configuration e watch_providers_ref "
            "atualizadas (movie e tv), Data Quality e Glue AGG disparados.",
        )

    def test_nao_chamado_quando_erro_em_genre_aborta_o_script(self, monkeypatch):
        with _patched_main(monkeypatch, genre_side_effect=RuntimeError("boom")) as mocks:
            with pytest.raises(RuntimeError):
                br.main()
        mocks["notify"].assert_not_called()

    def test_nao_chamado_quando_erro_em_configuration_aborta_o_script(self, monkeypatch):
        with _patched_main(monkeypatch, config_side_effect=RuntimeError("boom")) as mocks:
            with pytest.raises(RuntimeError):
                br.main()
        mocks["notify"].assert_not_called()


class TestCheckpoint:
    def test_valida_o_checkpoint_com_a_data_utc_de_hoje_como_chave(self, monkeypatch):
        with patch("backfill_referencias.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 9, 20, 23, 59, tzinfo=timezone.utc)
            mocks = _run_main(monkeypatch)
        mock_datetime.now.assert_called_once_with(timezone.utc)
        mocks["load"].assert_called_once_with(
            mocks["s3_client"], "bucket-temp-test", "referencias", 20260920, 20260920,
        )

    def test_sem_checkpoint_grava_uma_vez_por_unidade_na_ordem_de_processamento(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        assert mocks["saved"] == [
            {"movie:genre"},
            {"movie:genre", "movie:configuration"},
            {"movie:genre", "movie:configuration", "movie:watch_providers_ref"},
            {"movie:genre", "movie:configuration", "movie:watch_providers_ref", "tv:genre"},
            {
                "movie:genre", "movie:configuration", "movie:watch_providers_ref",
                "tv:genre", "tv:configuration",
            },
            TODAS_AS_UNIDADES,
        ]

    def test_grava_o_checkpoint_no_bucket_temp_com_o_mesmo_valor_nos_dois_argumentos_de_ano(self, monkeypatch):
        mocks = _run_main(monkeypatch)
        for c in mocks["save"].call_args_list:
            _, bucket, table_group, start_key, end_key, _completed = c.args
            assert (bucket, table_group) == ("bucket-temp-test", "referencias")
            assert start_key == end_key

    def test_retoma_pulando_as_unidades_de_movie_ja_concluidas(self, monkeypatch):
        mocks = _run_main(
            monkeypatch,
            completed={"movie:genre", "movie:configuration", "movie:watch_providers_ref"},
        )
        for chave in ("genre", "config", "wp"):
            assert [c.args[3] for c in mocks[chave].call_args_list] == ["tv"]
        tabelas_escritas = [c.kwargs["table_name"] for c in mocks["write"].call_args_list]
        assert sorted(tabelas_escritas) == ["tb_config_countries", "tb_genre_tv", "tb_wp_ref_tv"]
        assert mocks["trigger"].call_count == 3

    @pytest.mark.parametrize(
        ("table_type", "chave_mock"),
        [("genre", "genre"), ("configuration", "config"), ("watch_providers_ref", "wp")],
    )
    def test_pula_somente_a_unidade_ja_concluida(self, monkeypatch, table_type, chave_mock):
        mocks = _run_main(monkeypatch, completed={f"movie:{table_type}"})
        assert [c.args[3] for c in mocks[chave_mock].call_args_list] == ["tv"]
        for outra in {"genre", "config", "wp"} - {chave_mock}:
            assert [c.args[3] for c in mocks[outra].call_args_list] == ["movie", "tv"]
        assert len(mocks["write"].call_args_list) == 5

    def test_retomada_preserva_no_checkpoint_as_unidades_anteriores(self, monkeypatch):
        mocks = _run_main(monkeypatch, completed={"movie:genre"})
        assert mocks["saved"][0] == {"movie:genre", "movie:configuration"}
        assert mocks["saved"][-1] == TODAS_AS_UNIDADES

    def test_com_todas_as_unidades_concluidas_nao_recoleta_mas_roda_agg_notifica_e_limpa(self, monkeypatch):
        mocks = _run_main(monkeypatch, completed=set(TODAS_AS_UNIDADES))
        for chave in ("genre", "config", "wp", "write", "trigger", "save"):
            mocks[chave].assert_not_called()
        mocks["agg"].assert_called_once()
        mocks["notify"].assert_called_once()
        mocks["clear"].assert_called_once()

    def test_limpa_o_checkpoint_ao_final_depois_do_agg_e_da_notificacao(self, monkeypatch):
        with _patched_main(monkeypatch) as mocks:
            manager = MagicMock()
            manager.attach_mock(mocks["agg"], "agg")
            manager.attach_mock(mocks["notify"], "notify")
            manager.attach_mock(mocks["clear"], "clear")
            br.main()
        assert [c[0] for c in manager.mock_calls] == ["agg", "notify", "clear"]
        mocks["clear"].assert_called_once_with(mocks["s3_client"], "bucket-temp-test", "referencias")

    def test_nao_limpa_o_checkpoint_quando_erro_em_configuration_aborta(self, monkeypatch):
        with _patched_main(monkeypatch, config_side_effect=RuntimeError("boom")) as mocks:
            with pytest.raises(RuntimeError):
                br.main()
        # movie:genre já tinha sido concluída e fica salva para a próxima tentativa.
        assert mocks["saved"] == [{"movie:genre"}]
        mocks["clear"].assert_not_called()

    def test_http_error_em_watch_providers_ref_nao_entra_no_checkpoint(self, monkeypatch):
        mocks = _run_main(monkeypatch, collect_watch_providers_side_effect=[HTTPError("falhou"), None])
        assert "movie:watch_providers_ref" not in mocks["saved"][-1]
        assert mocks["saved"][-1] == TODAS_AS_UNIDADES - {"movie:watch_providers_ref"}
        # O script termina com sucesso mesmo assim, então o checkpoint é removido.
        mocks["clear"].assert_called_once()

    def test_token_expirado_na_escrita_preserva_o_checkpoint_e_sai_com_codigo_75(self, monkeypatch):
        # 1ª escrita (movie:genre) funciona; a 2ª (movie:configuration) perde a credencial.
        with _patched_main(monkeypatch, write_side_effect=[None, _token_expirado()]) as mocks:
            with pytest.raises(SystemExit) as exc_info:
                br.shared.run_with_retry_exit(br.main)
        assert exc_info.value.code == 75
        assert mocks["saved"] == [{"movie:genre"}]
        mocks["clear"].assert_not_called()
        mocks["agg"].assert_not_called()
        mocks["notify"].assert_not_called()

    def test_retry_apos_token_expirado_nao_refaz_a_unidade_ja_concluida(self, monkeypatch):
        # Simula a tentativa seguinte à do teste acima: load_checkpoint devolve o que foi salvo.
        mocks = _run_main(monkeypatch, completed={"movie:genre"})
        assert [c.args[3] for c in mocks["genre"].call_args_list] == ["tv"]
        assert [c.args[3] for c in mocks["config"].call_args_list] == ["movie", "tv"]


class TestErros:
    def test_erro_em_genre_aborta_o_backfill(self, monkeypatch):
        with _patched_main(monkeypatch, genre_side_effect=RuntimeError("boom")) as mocks:
            with pytest.raises(RuntimeError):
                br.main()
        mocks["config"].assert_not_called()
        mocks["agg"].assert_not_called()

    def test_http_error_em_watch_providers_ref_nao_aborta_mas_pula_a_escrita(self, monkeypatch):
        mocks = _run_main(
            monkeypatch,
            collect_watch_providers_side_effect=[HTTPError("falhou"), None],
        )
        # movie falhou (sem escrita de watch_providers_ref), tv teve sucesso normalmente.
        tabelas_escritas = [c.kwargs["table_name"] for c in mocks["write"].call_args_list]
        assert "tb_wp_ref_movie" not in tabelas_escritas
        assert "tb_wp_ref_tv" in tabelas_escritas
        # genre e configuration continuam sendo processados para os 2 content_types.
        assert [c.args[3] for c in mocks["genre"].call_args_list] == ["movie", "tv"]

    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("TMDB_SECRET_ARN", raising=False)
        with pytest.raises(EnvironmentError):
            br.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetSecretValue")
        assert br.shared.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "GetSecretValue")
        assert br.shared.expired_token_exit_code(exc) == 75
