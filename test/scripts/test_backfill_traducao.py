"""
Testa scripts/backfill_traducao.py com awswrangler, traduzir_texto e boto3
mockados (nenhuma chamada real à AWS ou ao Google Translate).

Foco: as funções puras (_adicionar_traducoes_pt, _backfill_year,
_load_discover_map) isoladamente, e a orquestração de main() via mocks dessas
funções — evita montar DataFrames grandes só para testar o loop de anos.
Retry/backoff da tradução em si é coberto em test/shared_src/test_traducao.py.
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
    "S3_BUCKET_TEMP": "bucket-temp-test",
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


class TestAdicionarTraducoesPt:
    def test_sem_registros_en_nao_chama_traducao(self):
        df = pd.DataFrame({"original_language": ["pt", "es"], "overview_en": ["c", "d"]})
        with patch("backfill_traducao.traduzir_texto") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_pt(df)
        mock_translate.assert_not_called()
        assert resultado["overview_pt"].isna().all()
        assert sucesso == 0

    def test_traduz_apenas_registros_en(self):
        df = pd.DataFrame({
            "original_language": ["en", "pt"],
            "overview_en": ["Overview", "Sinopse"],
        })
        with patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT"):
            resultado, sucesso = bt._adicionar_traducoes_pt(df)

        assert resultado.loc[0, "overview_pt"] == "Overview_PT"
        assert pd.isna(resultado.loc[1, "overview_pt"])
        assert sucesso == 1

    def test_nao_conta_como_sucesso_quando_traducao_falha_e_mantem_original(self):
        """traduzir_texto devolve o texto original quando falha após todas as tentativas."""
        df = pd.DataFrame({
            "original_language": ["en", "en"],
            "overview_en": ["Overview", "Falhou"],
        })
        with patch(
            "backfill_traducao.traduzir_texto",
            side_effect=lambda t: "Overview_PT" if t == "Overview" else t,
        ):
            resultado, sucesso = bt._adicionar_traducoes_pt(df)

        assert resultado.loc[0, "overview_pt"] == "Overview_PT"
        assert resultado.loc[1, "overview_pt"] == "Falhou"
        assert sucesso == 1

    def test_pula_registros_ja_traduzidos_com_sucesso(self):
        """overview_pt já preenchido e diferente do original não é retraduzido."""
        df = pd.DataFrame({
            "original_language": ["en", "en"],
            "overview_en": ["Já traduzido antes", "Ainda pendente"],
            "overview_pt": ["Already translated before", None],
        })
        with patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_pt(df)

        mock_translate.assert_called_once_with("Ainda pendente")
        assert resultado.loc[0, "overview_pt"] == "Already translated before"
        assert resultado.loc[1, "overview_pt"] == "Ainda pendente_PT"
        assert sucesso == 1

    def test_retenta_registro_cujo_overview_pt_ficou_igual_ao_original(self):
        """overview_pt == overview_en indica fallback de uma falha anterior — deve ser re-tentado."""
        df = pd.DataFrame({
            "original_language": ["en"],
            "overview_en": ["Falhou antes"],
            "overview_pt": ["Falhou antes"],
        })
        with patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_pt(df)

        mock_translate.assert_called_once_with("Falhou antes")
        assert resultado.loc[0, "overview_pt"] == "Falhou antes_PT"
        assert sucesso == 1

    def test_todos_ja_traduzidos_nao_chama_traducao(self):
        df = pd.DataFrame({
            "original_language": ["en", "en"],
            "overview_en": ["A", "B"],
            "overview_pt": ["A_PT", "B_PT"],
        })
        with patch("backfill_traducao.traduzir_texto") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_pt(df)

        mock_translate.assert_not_called()
        assert resultado.loc[0, "overview_pt"] == "A_PT"
        assert resultado.loc[1, "overview_pt"] == "B_PT"
        assert sucesso == 0


class TestAdicionarTraducoesTaglinePt:
    def test_sem_tagline_nao_chama_traducao(self):
        df = pd.DataFrame({"tagline": [None, ""]})
        with patch("backfill_traducao.traduzir_texto") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_tagline_pt(df)
        mock_translate.assert_not_called()
        assert sucesso == 0

    def test_traduz_qualquer_idioma_sem_filtro_original_language(self):
        """Diferente de overview_pt, tagline_pt não filtra por original_language (espelha glue_details)."""
        df = pd.DataFrame({
            "original_language": ["pt", "es"],
            "tagline": ["Uma frase.", "Otra frase."],
        })
        with patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_tagline_pt(df)

        assert mock_translate.call_count == 2
        assert resultado.loc[0, "tagline_pt"] == "Uma frase._PT"
        assert sucesso == 2

    def test_pula_registros_ja_traduzidos(self):
        df = pd.DataFrame({
            "tagline": ["Já traduzida", "Pendente"],
            "tagline_pt": ["Already translated", None],
        })
        with patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_tagline_pt(df)

        mock_translate.assert_called_once_with("Pendente")
        assert resultado.loc[0, "tagline_pt"] == "Already translated"
        assert resultado.loc[1, "tagline_pt"] == "Pendente_PT"
        assert sucesso == 1

    def test_retenta_registro_cujo_tagline_pt_ficou_igual_ao_original(self):
        df = pd.DataFrame({"tagline": ["Falhou antes"], "tagline_pt": ["Falhou antes"]})
        with patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_tagline_pt(df)

        mock_translate.assert_called_once_with("Falhou antes")
        assert resultado.loc[0, "tagline_pt"] == "Falhou antes_PT"
        assert sucesso == 1


class TestAdicionarTraducoesKeywordsPt:
    def test_sem_keywords_nao_chama_traducao(self):
        df = pd.DataFrame({"keywords": [None, ""]})
        with patch("backfill_traducao.traduzir_texto") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_keywords_pt(df)
        mock_translate.assert_not_called()
        assert sucesso == 0

    def test_traduz_qualquer_idioma_sem_filtro_original_language(self):
        """TMDB sempre devolve keywords em inglês, independente do idioma original do título."""
        df = pd.DataFrame({
            "original_language": ["pt"],
            "keywords": ["space, alien"],
        })
        with patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_keywords_pt(df)

        mock_translate.assert_called_once_with("space, alien")
        assert resultado.loc[0, "keywords_pt"] == "space, alien_PT"
        assert sucesso == 1

    def test_pula_registros_ja_traduzidos(self):
        df = pd.DataFrame({
            "keywords": ["já traduzida", "pendente"],
            "keywords_pt": ["already translated", None],
        })
        with patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT") as mock_translate:
            resultado, sucesso = bt._adicionar_traducoes_keywords_pt(df)

        mock_translate.assert_called_once_with("pendente")
        assert resultado.loc[0, "keywords_pt"] == "already translated"
        assert resultado.loc[1, "keywords_pt"] == "pendente_PT"
        assert sucesso == 1


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

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_loga_e_repropaga(self, caplog, codigo):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = ClientError(
                {"Error": {"Code": codigo, "Message": "expired"}}, "GetObject",
            )
            with caplog.at_level("ERROR", logger="backfill_traducao"):
                with pytest.raises(ClientError):
                    bt._load_discover_map("discover_movie", "bucket-sot-test")
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)


class TestBackfillYear:
    def test_sem_arquivos_retorna_false_e_nao_escreve(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = Exception("NoFilesFound: nada aqui")
            resultado, traduzidos = bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

        assert resultado is False
        assert traduzidos == 0
        mock_wr.s3.to_parquet.assert_not_called()

    def test_df_vazio_retorna_false_e_nao_escreve(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = pd.DataFrame()
            resultado, traduzidos = bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

        assert resultado is False
        assert traduzidos == 0
        mock_wr.s3.to_parquet.assert_not_called()

    def test_outras_excecoes_sao_repropagadas(self):
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = RuntimeError("acesso negado")
            with pytest.raises(RuntimeError, match="acesso negado"):
                bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_na_leitura_loga_e_repropaga(self, caplog, codigo):
        """Reproduz o erro real de produção: ListObjectsV2 (via wr.s3.read_parquet) retorna
        o código S3 'ExpiredToken', não o código STS 'ExpiredTokenException'."""
        with patch("backfill_traducao.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = ClientError(
                {"Error": {"Code": codigo, "Message": "expired"}}, "GetObject",
            )
            with caplog.at_level("ERROR", logger="backfill_traducao"):
                with pytest.raises(ClientError):
                    bt._backfill_year("db_movie", "details_movie", pd.DataFrame(), "2020", "bucket-sot-test")
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_na_escrita_loga_e_repropaga(self, caplog, codigo):
        details_df = pd.DataFrame({"id": [1], "overview_en": ["a"]})
        discover_map = pd.DataFrame({"id": [1], "original_language": ["en"]})

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            mock_wr.s3.to_parquet.side_effect = ClientError(
                {"Error": {"Code": codigo, "Message": "expired"}}, "PutObject",
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
            patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            resultado, traduzidos = bt._backfill_year("db_movie", "details_movie", discover_map, "2020", "bucket-sot-test")

        assert resultado is True
        assert traduzidos == 1  # só o id=1 é "en"; id=2 é "und" (original_language=None) e não é traduzido
        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert kwargs["path"] == "s3://bucket-sot-test/tmdb/details_movie/"
        assert kwargs["partition_cols"] == ["year"]
        assert kwargs["mode"] == "overwrite_partitions"
        assert kwargs["database"] == "db_movie"
        assert kwargs["table"] == "details_movie"
        assert "original_language" not in kwargs["df"].columns
        assert (kwargs["df"]["year"] == "2020").all()

    def test_soma_traduzidos_de_overview_tagline_e_keywords(self):
        """traduzidos retornado por _backfill_year é a soma dos três campos, não só overview_pt."""
        details_df = pd.DataFrame({
            "id": [1],
            "overview_en": ["Overview"],
            "tagline": ["Tagline"],
            "keywords": ["space, alien"],
        })
        discover_map = pd.DataFrame({"id": [1], "original_language": ["en"]})

        with (
            patch("backfill_traducao.wr") as mock_wr,
            patch("backfill_traducao.traduzir_texto", side_effect=lambda t: f"{t}_PT"),
        ):
            mock_wr.s3.read_parquet.return_value = details_df
            resultado, traduzidos = bt._backfill_year("db_movie", "details_movie", discover_map, "2020", "bucket-sot-test")

        assert resultado is True
        assert traduzidos == 3  # 1 overview_pt + 1 tagline_pt + 1 keywords_pt
        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        df_escrito = kwargs["df"]
        assert df_escrito.loc[0, "overview_pt"] == "Overview_PT"
        assert df_escrito.loc[0, "tagline_pt"] == "Tagline_PT"
        assert df_escrito.loc[0, "keywords_pt"] == "space, alien_PT"


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
        mock_backfill.return_value = (True, 0)
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

    def test_loga_total_de_traduzidos_com_sucesso_acumulado(self, monkeypatch, caplog):
        """O total no log final soma os traduzidos com sucesso de cada partição, não a quantidade de partições."""
        with (
            patch("backfill_traducao._load_discover_map") as mock_load,
            patch("backfill_traducao._backfill_year") as mock_backfill,
            patch("backfill_traducao.time.sleep"),
            patch("backfill_traducao.boto3") as mock_boto3,
        ):
            _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
            mock_load.return_value = pd.DataFrame({"id": [], "original_language": []})
            mock_backfill.side_effect = [(True, 7), (False, 0)]  # movie:2020 traduz 7, tv:2020 sem dados
            mock_boto3.client.return_value = _s3_client_sem_checkpoint()

            with caplog.at_level("INFO"):
                bt.main()

        resumo = [r.message for r in caplog.records if "Backfill de tradução concluído" in r.message]
        assert len(resumo) == 1
        assert "7 campos traduzidos com sucesso" in resumo[0]


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("S3_BUCKET_SOT", raising=False)
        with pytest.raises(EnvironmentError):
            bt.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetObject")
        assert bt.shared.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "GetObject")
        assert bt.shared.expired_token_exit_code(exc) == 75


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

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_checkpoint_reflete_progresso_parcial_quando_interrompido(self, monkeypatch, codigo):
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
                (True, 3),
                ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "GetObject"),
            ]
            with pytest.raises(ClientError):
                bt.main()

        assert mock_s3.put_object.call_count == 1
        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["movie:2020"]
