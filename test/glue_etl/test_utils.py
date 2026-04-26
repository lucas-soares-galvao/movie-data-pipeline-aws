class TestProcessarTmdb(unittest.TestCase):
    # ...existing code...

    @patch("app.glue_etl.src.utils.wr")
    def test_sem_particao_nao_adiciona_colunas(self, mock_wr):
        df = self._df_base()
        mock_wr.s3.read_json.return_value = df

        resultado = processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
            partition_cols=None
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["partition_cols"], [])
        self.assertNotIn("year", kwargs["df"].columns)
        self.assertNotIn("month", kwargs["df"].columns)

    @patch("app.glue_etl.src.utils.wr")
    def test_particao_customizada(self, mock_wr):
        df = self._df_base()
        mock_wr.s3.read_json.return_value = df

        resultado = processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
            partition_cols=["custom"]
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["partition_cols"], ["custom"])
"""Testes unitarios das funcoes utilitarias do Glue ETL."""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from app.glue_etl.src.utils import processar_tmdb


class TestProcessarTmdb(unittest.TestCase):
    def _make_fake_wr(self, df):
        fake_wr = MagicMock()
        fake_wr.s3.read_json.return_value = df
        return fake_wr

    def _df_base(self):
        return pd.DataFrame(
            [
                {
                    "id": 1,
                    "title": "Filme 1",
                    "release_date": "2024-03-15",
                    "popularity": 8.4,
                    "vote_average": 7.9,
                    "vote_count": 120,
                }
            ]
        )

    @patch("app.glue_etl.src.utils.wr")
    def test_le_json_do_s3_e_escreve_parquet(self, mock_wr):
        mock_wr.s3.read_json.return_value = self._df_base()

        resultado = processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
        )

        mock_wr.s3.read_json.assert_called_once_with("s3://bucket-sor/")
        mock_wr.s3.to_parquet.assert_called_once()

    @patch("app.glue_etl.src.utils.wr")
    def test_adiciona_colunas_year_e_month(self, mock_wr):
        mock_wr.s3.read_json.return_value = self._df_base()

        processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        df_gravado = kwargs["df"]
        self.assertIn("year", df_gravado.columns)
        self.assertIn("month", df_gravado.columns)
        self.assertEqual(df_gravado.iloc[0]["year"], "2024")
        self.assertEqual(df_gravado.iloc[0]["month"], "03")

    @patch("app.glue_etl.src.utils.wr")
    def test_to_parquet_chamado_com_particoes_e_catalogo(self, mock_wr):
        mock_wr.s3.read_json.return_value = self._df_base()

        processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["path"], "s3://bucket-sot/")
        self.assertEqual(kwargs["database"], "tmdb_dev")
        self.assertEqual(kwargs["table"], "movies_sot")
        self.assertEqual(kwargs["partition_cols"], ["year", "month"])
        self.assertEqual(kwargs["mode"], "overwrite")

    @patch("app.glue_etl.src.utils.wr")
    def test_retorna_linhas_processadas(self, mock_wr):
        df = pd.concat([self._df_base(), self._df_base()], ignore_index=True)
        mock_wr.s3.read_json.return_value = df

        resultado = processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
        )

        self.assertEqual(resultado["linhas_processadas"], 2)

    @patch("app.glue_etl.src.utils.wr")
    def test_release_date_invalida_nao_levanta_excecao(self, mock_wr):
        df = pd.DataFrame(
            [{"id": 1, "title": "Sem Data", "release_date": "invalido"}]
        )
        mock_wr.s3.read_json.return_value = df

        resultado = processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
        )

        self.assertEqual(resultado["linhas_processadas"], 1)


if __name__ == "__main__":
    unittest.main()
