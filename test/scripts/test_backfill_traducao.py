"""
Testa scripts/backfill_traducao.py com awswrangler, GoogleTranslator e boto3
mockados (nenhuma chamada real à AWS ou ao Google Translate).

Foco: as funções puras (_translate, _adicionar_traducoes_pt, _backfill_year,
_load_discover_map) isoladamente, e a orquestração de main() via mocks dessas
funções — evita montar DataFrames grandes só para testar o loop de anos.
"""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError

import backfill_traducao as bt

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "TABLE_GROUP": "traducao",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_DETAILS_MOVIE": "details_movie",
    "TABLE_DETAILS_TV": "details_tv",
    "TABLE_DISCOVER_MOVIE": "discover_movie",
    "TABLE_DISCOVER_TV": "discover_tv",
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


class TestTranslate:
    def test_string_vazia_retorna_vazia_sem_chamar_google(self):
        with patch("backfill_traducao.GoogleTranslator") as mock_google:
            assert bt._translate("") == ""
        mock_google.assert_not_called()

    def test_traduz_com_sucesso_na_primeira_tentativa(self):
        with patch("backfill_traducao.GoogleTranslator") as mock_google:
            mock_google.return_value.translate.return_value = "traduzido"
            assert bt._translate("hello") == "traduzido"
        assert mock_google.return_value.translate.call_count == 1

    def test_tenta_novamente_apos_excecao_e_depois_sucede(self):
        with (
            patch("backfill_traducao.GoogleTranslator") as mock_google,
            patch("backfill_traducao.time.sleep"),
        ):
            mock_google.return_value.translate.side_effect = [Exception("timeout"), "traduzido"]
            assert bt._translate("hello") == "traduzido"
        assert mock_google.return_value.translate.call_count == 2

    def test_retorna_texto_original_apos_tres_falhas(self):
        with (
            patch("backfill_traducao.GoogleTranslator") as mock_google,
            patch("backfill_traducao.time.sleep"),
        ):
            mock_google.return_value.translate.side_effect = Exception("timeout")
            assert bt._translate("hello") == "hello"
        assert mock_google.return_value.translate.call_count == 3


class TestAdicionarTraducoesPt:
    def test_sem_registros_en_nao_chama_traducao(self):
        df = pd.DataFrame({"original_language": ["pt", "es"], "overview_en": ["c", "d"]})
        with patch("backfill_traducao._translate") as mock_translate:
            resultado = bt._adicionar_traducoes_pt(df)
        mock_translate.assert_not_called()
        assert resultado["overview_pt"].isna().all()

    def test_traduz_apenas_registros_en(self):
        df = pd.DataFrame({
            "original_language": ["en", "pt"],
            "overview_en": ["Overview", "Sinopse"],
        })
        with patch("backfill_traducao._translate", side_effect=lambda t: f"{t}_PT"):
            resultado = bt._adicionar_traducoes_pt(df)

        assert resultado.loc[0, "overview_pt"] == "Overview_PT"
        assert pd.isna(resultado.loc[1, "overview_pt"])


class TestLoadDiscoverMap:
    def test_remove_duplicatas_e_seleciona_colunas(self):
        df_bruto = pd.DataFrame({
            "id": [1, 1, 2],
            "original_language": ["en", "en", "pt"],
            "coluna_extra": ["x", "y", "z"],
        })
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = df_bruto
            resultado = bt._load_discover_map("discover_movie", "bucket-sot-test")

        mock_wr.s3.read_parquet.assert_called_once_with(
            path="s3://bucket-sot-test/tmdb/discover_movie/", columns=["id", "original_language"],
        )
        assert list(resultado.columns) == ["id", "original_language"]
        assert len(resultado) == 2

    def test_expired_token_loga_e_repropaga(self, caplog):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = ClientError(
                {"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "GetObject",
            )
            with caplog.at_level("ERROR", logger="backfill_traducao"):
                with pytest.raises(ClientError):
                    bt._load_discover_map("discover_movie", "bucket-sot-test")
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestBackfillYear:
    def test_sem_arquivos_retorna_false_e_nao_escreve(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = Exception("NoFilesFound: nada aqui")
            resultado = bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

        assert resultado is False
        mock_wr.s3.to_parquet.assert_not_called()

    def test_df_vazio_retorna_false_e_nao_escreve(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = pd.DataFrame()
            resultado = bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

        assert resultado is False
        mock_wr.s3.to_parquet.assert_not_called()

    def test_outras_excecoes_sao_repropagadas(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = RuntimeError("acesso negado")
            with pytest.raises(RuntimeError, match="acesso negado"):
                bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

    def test_expired_token_na_leitura_loga_e_repropaga(self, caplog):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = ClientError(
                {"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "GetObject",
            )
            with caplog.at_level("ERROR", logger="backfill_traducao"):
                with pytest.raises(ClientError):
                    bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    def test_expired_token_na_escrita_loga_e_repropaga(self, caplog):
        details_df = pd.DataFrame({"id": [1], "overview_en": ["a"]})
        discover_map = pd.DataFrame({"id": [1], "original_language": ["en"]})

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao._translate", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            mock_wr.s3.to_parquet.side_effect = ClientError(
                {"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "PutObject",
            )
            with caplog.at_level("ERROR", logger="backfill_traducao"):
                with pytest.raises(ClientError):
                    bt._backfill_year("db_movie", "details_movie", discover_map, "2020", "bucket-sot-test")
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    def test_escreve_com_particao_e_modo_overwrite_partitions(self):
        details_df = pd.DataFrame({
            "id": [1, 2],
            "overview_en": ["a", "b"],
        })
        discover_map = pd.DataFrame({"id": [1, 2], "original_language": ["en", None]})

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao._translate", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            resultado = bt._backfill_year("db_movie", "details_movie", discover_map, "2020", "bucket-sot-test")

        assert resultado is True
        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert kwargs["path"] == "s3://bucket-sot-test/tmdb/details_movie/"
        assert kwargs["partition_cols"] == ["year"]
        assert kwargs["mode"] == "overwrite_partitions"
        assert kwargs["database"] == "db_movie"
        assert kwargs["table"] == "details_movie"
        assert "original_language" not in kwargs["df"].columns
        assert (kwargs["df"]["year"] == "2020").all()


def _run_main(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None, mock_s3: MagicMock | None = None):
    _set_env(monkeypatch, overrides)
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()
    with (
        patch("backfill_traducao._load_discover_map") as mock_load,
        patch("backfill_traducao._backfill_year") as mock_backfill,
        patch("backfill_traducao.time.sleep") as mock_sleep,
        patch("backfill_traducao.boto3") as mock_boto3,
    ):
        mock_load.return_value = pd.DataFrame({"id": [], "original_language": []})
        mock_boto3.client.return_value = mock_s3
        bt.main()
    return mock_load, mock_backfill, mock_sleep, mock_s3


class TestMain:
    def test_carrega_discover_map_uma_vez_por_tipo(self, monkeypatch):
        mock_load, _, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_load.call_count == 2  # movie + tv, independente do numero de anos

    def test_backfill_year_chamado_para_cada_ano_e_tipo(self, monkeypatch):
        _, mock_backfill, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2022"})
        assert mock_backfill.call_count == 6  # 3 anos x 2 tipos

    def test_alterna_movie_e_tv_por_ano(self, monkeypatch):
        _, mock_backfill, _, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        databases = [c.kwargs["database"] for c in mock_backfill.call_args_list]
        assert databases == ["db_movie", "db_tv"]

    def test_nao_pausa_apos_ultima_chamada(self, monkeypatch):
        _, mock_backfill, mock_sleep, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_sleep.call_count == mock_backfill.call_count - 1


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("S3_BUCKET_SOT", raising=False)
        with pytest.raises(EnvironmentError):
            bt.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetObject")
        assert bt.checkpoint.expired_token_exit_code(exc) is None

    def test_expired_token_gera_codigo_75(self):
        exc = ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "x"}}, "GetObject")
        assert bt.checkpoint.expired_token_exit_code(exc) == 75


class TestCheckpoint:
    def test_pula_particoes_ja_concluidas(self, monkeypatch):
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=json.dumps(
                {"start_year": 2020, "end_year": 2021, "completed": ["movie:2020", "tv:2020"]}
            ).encode()))
        }

        _, mock_backfill, _, _ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"}, mock_s3=mock_s3,
        )

        anos = [(c.kwargs["database"], c.kwargs["year"]) for c in mock_backfill.call_args_list]
        assert anos == [("db_movie", "2021"), ("db_tv", "2021")]

    def test_salva_checkpoint_apos_cada_particao(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        assert mock_s3.put_object.call_count == 2  # movie:2020, tv:2020

    def test_marca_completo_mesmo_quando_backfill_year_retorna_false(self, monkeypatch):
        """Nenhum arquivo/registro para a partição ainda conta como concluído (nada para fazer, não é falha)."""
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3,
        )

        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["movie:2020", "tv:2020"]

    def test_limpa_checkpoint_ao_concluir_tudo_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()

        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)

        mock_s3.delete_object.assert_called_once()

    def test_checkpoint_reflete_progresso_parcial_quando_interrompido(self, monkeypatch):
        _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        mock_s3 = _s3_client_sem_checkpoint()

        with (
            patch("backfill_traducao._load_discover_map") as mock_load,
            patch("backfill_traducao._backfill_year") as mock_backfill,
            patch("backfill_traducao.time.sleep"),
            patch("backfill_traducao.boto3") as mock_boto3,
        ):
            mock_load.return_value = pd.DataFrame({"id": [], "original_language": []})
            mock_boto3.client.return_value = mock_s3
            mock_backfill.side_effect = [
                True,
                ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "expired"}}, "GetObject"),
            ]
            with pytest.raises(ClientError):
                bt.main()

        assert mock_s3.put_object.call_count == 1
        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["movie:2020"]
