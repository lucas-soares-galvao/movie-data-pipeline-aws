"""
Testa scripts/backfill_rename_colunas.py com awswrangler e boto3 mockados
(nenhuma chamada real à AWS).

Foco: _rename_partition_column isolada (leitura/coalesce/escrita/guard de schema
já migrado) e a orquestração de main() via mock dessa função — evita montar
DataFrames grandes só para testar o loop de tabelas x anos.
"""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError

import backfill_rename_colunas as brc

ENV_BASE = {
    "AWS_REGION": "sa-east-1",
    "TABLE_GROUP": "rename_colunas",
    "S3_BUCKET_SOT": "bucket-sot-test",
    "S3_BUCKET_TEMP": "bucket-temp-test",
    "GLUE_DATABASE_MOVIE": "db_movie",
    "GLUE_DATABASE_TV": "db_tv",
    "TABLE_DETAILS_MOVIE": "details_movie",
    "TABLE_DETAILS_TV": "details_tv",
    "TABLE_WATCH_PROVIDERS_MOVIE": "watch_providers_movie",
    "TABLE_WATCH_PROVIDERS_TV": "watch_providers_tv",
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


class TestRenamePartitionColumn:
    def test_sem_arquivos_retorna_false_e_nao_escreve(self):
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = Exception("NoFilesFound: nada aqui")
            resultado = brc._rename_partition_column(
                "db_movie", "details_movie", "2020", "bucket-sot-test", "dt_processamento", "processed_date",
            )
        assert resultado is False
        mock_wr.s3.to_parquet.assert_not_called()

    def test_df_vazio_retorna_false_e_nao_escreve(self):
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = pd.DataFrame()
            resultado = brc._rename_partition_column(
                "db_movie", "details_movie", "2020", "bucket-sot-test", "dt_processamento", "processed_date",
            )
        assert resultado is False
        mock_wr.s3.to_parquet.assert_not_called()

    def test_particao_ja_migrada_sem_coluna_antiga_retorna_false_e_nao_escreve(self):
        """Guard central do script: partição sem a coluna antiga no schema físico
        (já migrada por este script ou já 100% escrita pelo pipeline normal desde
        o rename) não deve ser regravada de novo."""
        df = pd.DataFrame({"id": [1, 2], "processed_date": ["2026-01-01", "2026-01-02"]})
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = df
            resultado = brc._rename_partition_column(
                "db_movie", "details_movie", "2020", "bucket-sot-test", "dt_processamento", "processed_date",
            )
        assert resultado is False
        mock_wr.s3.to_parquet.assert_not_called()

    def test_outras_excecoes_sao_repropagadas(self):
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = RuntimeError("acesso negado")
            with pytest.raises(RuntimeError, match="acesso negado"):
                brc._rename_partition_column(
                    "db_movie", "details_movie", "2020", "bucket-sot-test", "dt_processamento", "processed_date",
                )

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_na_leitura_loga_e_repropaga(self, caplog, codigo):
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.side_effect = ClientError(
                {"Error": {"Code": codigo, "Message": "expired"}}, "GetObject",
            )
            with caplog.at_level("ERROR", logger="backfill_rename_colunas"):
                with pytest.raises(ClientError):
                    brc._rename_partition_column(
                        "db_movie", "details_movie", "2020", "bucket-sot-test", "dt_processamento", "processed_date",
                    )
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_na_escrita_loga_e_repropaga(self, caplog, codigo):
        df = pd.DataFrame({"id": [1], "dt_processamento": ["2025-01-01"]})
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = df
            mock_wr.s3.to_parquet.side_effect = ClientError(
                {"Error": {"Code": codigo, "Message": "expired"}}, "PutObject",
            )
            with caplog.at_level("ERROR", logger="backfill_rename_colunas"):
                with pytest.raises(ClientError):
                    brc._rename_partition_column(
                        "db_movie", "details_movie", "2020", "bucket-sot-test", "dt_processamento", "processed_date",
                    )
        assert any("Credenciais AWS expiraram" in r.message for r in caplog.records)

    def test_particao_totalmente_nao_migrada_preenche_coluna_nova_e_descarta_antiga(self):
        """Caso comum: partição nunca tocada pelo pipeline desde o rename — só tem
        a coluna antiga. Todo registro deve ganhar a coluna nova a partir dela."""
        df = pd.DataFrame({
            "id": [1, 2],
            "dt_processamento": ["2020-05-01", "2020-05-02"],
        })
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = df
            resultado = brc._rename_partition_column(
                "db_movie", "details_movie", "2020", "bucket-sot-test", "dt_processamento", "processed_date",
            )

        assert resultado is True
        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        df_escrito = kwargs["df"]
        assert "dt_processamento" not in df_escrito.columns
        assert list(df_escrito["processed_date"]) == ["2020-05-01", "2020-05-02"]

    def test_particao_mista_preserva_coluna_nova_e_usa_antiga_so_para_os_nulos(self):
        """Caso do IDs que saíram do discover atual: parte dos registros já foi
        reprocessada pelo pipeline normal (tem processed_date), parte ainda só
        tem dt_processamento (preservada pelo merge de collect_and_write_details).
        Coalesce não deve sobrescrever quem já tem o valor novo."""
        df = pd.DataFrame({
            "id":               [1,            2,      3],
            "processed_date":   ["2026-07-19", None,   None],
            "dt_processamento": [None,         "2020-05-02", "2020-05-03"],
        })
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = df
            resultado = brc._rename_partition_column(
                "db_movie", "details_movie", "2020", "bucket-sot-test", "dt_processamento", "processed_date",
            )

        assert resultado is True
        df_escrito = mock_wr.s3.to_parquet.call_args.kwargs["df"]
        assert "dt_processamento" not in df_escrito.columns
        assert list(df_escrito["processed_date"]) == ["2026-07-19", "2020-05-02", "2020-05-03"]

    def test_escreve_com_particao_e_modo_overwrite_partitions(self):
        df = pd.DataFrame({"id": [1], "dt_atualizacao": ["2025-06-01"]})
        with patch("backfill_rename_colunas.wr") as mock_wr:
            mock_wr.s3.read_parquet.return_value = df
            brc._rename_partition_column(
                "db_movie", "watch_providers_movie", "2020", "bucket-sot-test", "dt_atualizacao", "updated_date",
            )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        assert kwargs["path"] == "s3://bucket-sot-test/tmdb/watch_providers_movie/"
        assert kwargs["partition_cols"] == ["year"]
        assert kwargs["mode"] == "overwrite_partitions"
        assert kwargs["database"] == "db_movie"
        assert kwargs["table"] == "watch_providers_movie"
        assert (kwargs["df"]["year"] == "2020").all()


def _run_main(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None, mock_s3: MagicMock | None = None):
    _set_env(monkeypatch, overrides)
    mock_s3 = mock_s3 if mock_s3 is not None else _s3_client_sem_checkpoint()
    with (
        patch("backfill_rename_colunas._rename_partition_column") as mock_rename,
        patch("backfill_rename_colunas.boto3") as mock_boto3,
    ):
        mock_rename.return_value = True
        mock_boto3.client.return_value = mock_s3
        brc.main()
    return mock_rename, mock_s3


class TestMain:
    def test_chama_rename_para_cada_tabela_e_ano(self, monkeypatch):
        mock_rename, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2021"})
        assert mock_rename.call_count == 8  # 2 anos x 4 tabelas

    def test_percorre_as_quatro_tabelas_com_as_colunas_corretas_dentro_de_cada_ano(self, monkeypatch):
        mock_rename, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        chamadas = [
            (c.kwargs["table_name"], c.kwargs["old_column"], c.kwargs["new_column"])
            for c in mock_rename.call_args_list
        ]
        assert chamadas == [
            ("details_movie", "dt_processamento", "processed_date"),
            ("details_tv", "dt_processamento", "processed_date"),
            ("watch_providers_movie", "dt_atualizacao", "updated_date"),
            ("watch_providers_tv", "dt_atualizacao", "updated_date"),
        ]

    def test_usa_ano_atual_como_default_de_end_year(self, monkeypatch):
        from datetime import datetime
        mock_rename, _ = _run_main(monkeypatch, {"BACKFILL_START_YEAR": str(datetime.now().year)})
        assert mock_rename.call_count == 4  # 1 ano x 4 tabelas

    def test_loga_total_de_particoes_regravadas(self, monkeypatch, caplog):
        with (
            patch("backfill_rename_colunas._rename_partition_column") as mock_rename,
            patch("backfill_rename_colunas.boto3") as mock_boto3,
        ):
            _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
            mock_rename.side_effect = [True, True, False, True]  # 1 tabela já migrada (watch_providers_movie)
            mock_boto3.client.return_value = _s3_client_sem_checkpoint()

            with caplog.at_level("INFO"):
                brc.main()

        resumo = [r.message for r in caplog.records if "Backfill de rename de colunas concluído" in r.message]
        assert len(resumo) == 1
        assert "3 de 4 partições regravadas" in resumo[0]


class TestErros:
    def test_variavel_de_ambiente_obrigatoria_ausente_leva_a_erro(self, monkeypatch):
        _set_env(monkeypatch)
        monkeypatch.delenv("S3_BUCKET_SOT", raising=False)
        with pytest.raises(EnvironmentError):
            brc.main()

    def test_outro_erro_nao_gera_codigo_de_retomada(self):
        exc = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetObject")
        assert brc.shared.expired_token_exit_code(exc) is None

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_expired_token_gera_codigo_75(self, codigo):
        exc = ClientError({"Error": {"Code": codigo, "Message": "x"}}, "GetObject")
        assert brc.shared.expired_token_exit_code(exc) == 75


class TestCheckpoint:
    def test_pula_particoes_ja_concluidas(self, monkeypatch):
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=json.dumps({
                "start_year": 2020, "end_year": 2020,
                "completed": ["details_movie:2020", "details_tv:2020"],
            }).encode()))
        }

        mock_rename, _ = _run_main(
            monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3,
        )

        tabelas = [c.kwargs["table_name"] for c in mock_rename.call_args_list]
        assert tabelas == ["watch_providers_movie", "watch_providers_tv"]

    def test_salva_checkpoint_apos_cada_particao(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)
        assert mock_s3.put_object.call_count == 4  # 4 tabelas

    def test_marca_completo_mesmo_quando_rename_retorna_false(self, monkeypatch):
        """Partição já migrada (_rename_partition_column retorna False) ainda conta
        como concluída — não é falha, não deve ser reprocessada de novo."""
        mock_s3 = _s3_client_sem_checkpoint()
        with (
            patch("backfill_rename_colunas._rename_partition_column", return_value=False),
            patch("backfill_rename_colunas.boto3") as mock_boto3,
        ):
            _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
            mock_boto3.client.return_value = mock_s3
            brc.main()

        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert len(body["completed"]) == 4

    def test_limpa_checkpoint_ao_concluir_tudo_com_sucesso(self, monkeypatch):
        mock_s3 = _s3_client_sem_checkpoint()
        _run_main(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"}, mock_s3=mock_s3)
        mock_s3.delete_object.assert_called_once()

    @pytest.mark.parametrize("codigo", ["ExpiredTokenException", "ExpiredToken"])
    def test_checkpoint_reflete_progresso_parcial_quando_interrompido(self, monkeypatch, codigo):
        _set_env(monkeypatch, {"BACKFILL_START_YEAR": "2020", "BACKFILL_END_YEAR": "2020"})
        mock_s3 = _s3_client_sem_checkpoint()

        with (
            patch("backfill_rename_colunas._rename_partition_column") as mock_rename,
            patch("backfill_rename_colunas.boto3") as mock_boto3,
        ):
            mock_boto3.client.return_value = mock_s3
            mock_rename.side_effect = [
                True,
                ClientError({"Error": {"Code": codigo, "Message": "expired"}}, "GetObject"),
            ]
            with pytest.raises(ClientError):
                brc.main()

        assert mock_s3.put_object.call_count == 1
        body = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert body["completed"] == ["details_movie:2020"]
