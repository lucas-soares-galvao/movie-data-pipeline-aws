"""Testes unitarios das funcoes utilitarias do Glue ETL."""

import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from app.glue_etl.src.utils import processar_tmdb

class TestProcessarTmdb(unittest.TestCase):
    @patch("app.glue_etl.src.utils.wr")
    def test_particao_year_month(self, mock_wr):
        df = self._df_base()
        mock_wr.s3.read_json.return_value = df

        resultado = processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
            partition_cols=["year", "month"],
            partition_date_col="release_date"
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["partition_cols"], ["year", "month"])
        self.assertIn("year", kwargs["df"].columns)
        self.assertIn("month", kwargs["df"].columns)
    def _df_base(self):
        return pd.DataFrame({
            "id": [1, 2, 3],
            "title": ["Movie 1", "Movie 2", "Movie 3"],
            "release_date": ["2023-01-01", "2023-02-01", "2023-03-01"]
        })

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
        df["custom"] = ["A", "B", "C"]  # Simula coluna customizada
        mock_wr.s3.read_json.return_value = df

        resultado = processar_tmdb(
            input_path="s3://bucket-sor/",
            output_path="s3://bucket-sot/",
            database="tmdb_dev",
            table="movies_sot",
            partition_cols=["custom"],
            partition_date_col="custom"
        )

        kwargs = mock_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["partition_cols"], ["custom"])

if __name__ == "__main__":
    unittest.main()
