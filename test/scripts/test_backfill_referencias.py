"""
Testa scripts/backfill_referencias.py com collect_genre_data/collect_configuration_data/
collect_watch_providers_ref/read_from_sor/write_parquet_to_sot/trigger_glue_job/get_api_secret
mockados (nenhuma chamada real à AWS/TMDB).

Foco: a orquestração do backfill (independente da Lambda e do Glue ETL desde que o script passou
a rodar a coleta + transformação diretamente no processo — ver
app/lambda_api/lambda_api.md, seção "Backfill manual"): quais tabelas são processadas por
content_type, o contrato "erro em genre/configuration aborta, HTTPError em watch_providers_ref
não aborta" e o disparo do Glue Data Quality uma vez por tabela gravada. A lógica de negócio em
si (collect_genre_data, read_from_sor, write_parquet_to_sot) é testada em
test/lambda_api/test_utils.py e test/glue_etl/test_utils.py.
"""

from unittest.mock import MagicMock, call, patch

import backfill_referencias as br
import pytest
from botocore.exceptions import ClientError
from requests.exceptions import HTTPError

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "S3_BUCKET_SOR": "bucket-sor-test",
    "S3_BUCKET_SOT": "bucket-sot-test",
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
}


def _set_env(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> None:
    for key, value in {**ENV_BASE, **(overrides or {})}.items():
        monkeypatch.setenv(key, value)


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict | None = None,
    collect_watch_providers_side_effect=None,
):
    """Roda br.main() com as coletas TMDB, read_from_sor/write_parquet_to_sot e trigger_glue_job
    mockados. Retorna os mocks relevantes para inspeção nos testes."""
    _set_env(monkeypatch, overrides)

    with (
        patch("backfill_referencias.boto3") as mock_boto3,
        patch("backfill_referencias.get_api_secret", return_value="tmdb-key") as mock_secret,
        patch("backfill_referencias.collect_genre_data") as mock_genre,
        patch("backfill_referencias.collect_configuration_data") as mock_config,
        patch("backfill_referencias.collect_watch_providers_ref") as mock_wp,
        patch("backfill_referencias.read_from_sor", return_value="df-fake") as mock_read,
        patch("backfill_referencias.write_parquet_to_sot") as mock_write,
        patch("backfill_referencias.trigger_glue_job") as mock_trigger,
    ):
        mock_boto3.client.return_value = MagicMock()
        if collect_watch_providers_side_effect is not None:
            mock_wp.side_effect = collect_watch_providers_side_effect
        br.main()

    return {
        "secret": mock_secret,
        "genre": mock_genre,
        "config": mock_config,
        "wp": mock_wp,
        "read": mock_read,
        "write": mock_write,
        "trigger": mock_trigger,
    }


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


class TestErros:
    def test_erro_em_genre_aborta_o_backfill(self, monkeypatch):
        _set_env(monkeypatch)
        with (
            patch("backfill_referencias.boto3") as mock_boto3,
            patch("backfill_referencias.get_api_secret", return_value="tmdb-key"),
            patch("backfill_referencias.collect_genre_data", side_effect=RuntimeError("boom")),
            patch("backfill_referencias.collect_configuration_data") as mock_config,
            patch("backfill_referencias.read_from_sor"),
            patch("backfill_referencias.write_parquet_to_sot"),
            patch("backfill_referencias.trigger_glue_job"),
            pytest.raises(RuntimeError),
        ):
            mock_boto3.client.return_value = MagicMock()
            br.main()
        mock_config.assert_not_called()

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
