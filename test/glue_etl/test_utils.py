"""Testes unitarios das funcoes utilitarias do Glue ETL."""

import unittest
from unittest.mock import MagicMock

import pandas as pd

from app.glue_etl.src.utils import carregar_sor_json_para_tabela_sot, obter_valor_argumento


class TestObterValorArgumento(unittest.TestCase):
    def test_retorna_valor_quando_argumento_existe(self):
        argv = ["main.py", "--S3_BUCKET_SOR", "bucket-sor"]
        self.assertEqual(obter_valor_argumento(argv, "S3_BUCKET_SOR"), "bucket-sor")

    def test_retorna_none_quando_argumento_nao_existe(self):
        argv = ["main.py", "--outra-flag", "valor"]
        self.assertIsNone(obter_valor_argumento(argv, "S3_BUCKET_SOR"))


class TestCarregarSorJsonParaTabelaSot(unittest.TestCase):
    def test_normaliza_payload_lista_por_arquivo(self):
        fake_wr = MagicMock()
        fake_wr.s3.read_json.return_value = pd.DataFrame(
            [
                {
                    "0": [
                        {
                            "id": 100,
                            "title": "Filme A",
                            "original_title": "Movie A",
                            "overview": "Resumo A",
                            "release_date": "2024-01-01",
                            "original_language": "pt",
                            "adult": False,
                            "video": False,
                            "genre_ids": [18],
                            "popularity": 5.0,
                            "vote_average": 7.1,
                            "vote_count": 10,
                        },
                        {
                            "id": 101,
                            "title": "Filme B",
                            "original_title": "Movie B",
                            "overview": "Resumo B",
                            "release_date": "2024-01-02",
                            "original_language": "en",
                            "adult": False,
                            "video": False,
                            "genre_ids": [28],
                            "popularity": 6.0,
                            "vote_average": 7.3,
                            "vote_count": 12,
                        },
                    ],
                    "year": "2024",
                    "month": "01",
                }
            ]
        )

        resultado = carregar_sor_json_para_tabela_sot(
            s3_bucket_sor="bucket-sor",
            s3_bucket_sot="bucket-sot",
            catalog_database="tmdb_dev",
            catalog_table="movies_sot",
            wr_module=fake_wr,
        )

        kwargs = fake_wr.s3.to_parquet.call_args.kwargs
        df_gravado = kwargs["df"]
        self.assertEqual(len(df_gravado), 2)
        self.assertEqual(df_gravado.iloc[0]["id"], 100)
        self.assertEqual(df_gravado.iloc[1]["id"], 101)
        self.assertEqual(resultado["total_records"], 2)

    def test_escreve_dataset_parquet_no_catalogo(self):
        fake_wr = MagicMock()
        fake_wr.s3.read_json.return_value = pd.DataFrame(
            [
                {
                    "id": 1,
                    "title": "Filme 1",
                    "original_title": "Movie 1",
                    "overview": "Resumo",
                    "release_date": "2024-01-15",
                    "original_language": "pt",
                    "adult": False,
                    "video": False,
                    "genre_ids": [18, 35],
                    "popularity": 8.4,
                    "vote_average": 7.9,
                    "vote_count": 120,
                    "year": "2024",
                    "month": "1",
                }
            ]
        )

        resultado = carregar_sor_json_para_tabela_sot(
            s3_bucket_sor="bucket-sor",
            s3_bucket_sot="bucket-sot",
            catalog_database="tmdb_dev",
            catalog_table="movies_sot",
            wr_module=fake_wr,
        )

        fake_wr.s3.read_json.assert_called_once_with(
            path="s3://bucket-sor/tmdb/discover_movie/",
            dataset=True,
        )
        fake_wr.s3.to_parquet.assert_called_once()

        kwargs = fake_wr.s3.to_parquet.call_args.kwargs
        self.assertEqual(kwargs["path"], "s3://bucket-sot/tmdb/movies_sot/")
        self.assertEqual(kwargs["database"], "tmdb_dev")
        self.assertEqual(kwargs["table"], "movies_sot")
        self.assertEqual(kwargs["partition_cols"], ["year", "month"])
        self.assertEqual(kwargs["mode"], "overwrite_partitions")

        df_gravado = kwargs["df"]
        self.assertListEqual(list(df_gravado.columns), [
            "id",
            "title",
            "original_title",
            "overview",
            "release_date",
            "original_language",
            "adult",
            "video",
            "genre_ids",
            "popularity",
            "vote_average",
            "vote_count",
            "year",
            "month",
        ])
        self.assertEqual(df_gravado.iloc[0]["month"], "01")
        self.assertEqual(resultado["status"], "written")
        self.assertEqual(resultado["total_records"], 1)

    def test_retorna_no_data_quando_nao_ha_registros(self):
        fake_wr = MagicMock()
        fake_wr.s3.read_json.return_value = pd.DataFrame()

        resultado = carregar_sor_json_para_tabela_sot(
            s3_bucket_sor="bucket-sor",
            s3_bucket_sot="bucket-sot",
            catalog_database="tmdb_dev",
            catalog_table="movies_sot",
            wr_module=fake_wr,
        )

        fake_wr.s3.to_parquet.assert_not_called()
        self.assertEqual(resultado["status"], "no_data")
        self.assertEqual(resultado["total_records"], 0)

    def test_falha_sem_colunas_de_particao(self):
        fake_wr = MagicMock()
        fake_wr.s3.read_json.return_value = pd.DataFrame([{"id": 1, "title": "Filme"}])

        with self.assertRaises(ValueError):
            carregar_sor_json_para_tabela_sot(
                s3_bucket_sor="bucket-sor",
                s3_bucket_sot="bucket-sot",
                catalog_database="tmdb_dev",
                catalog_table="movies_sot",
                wr_module=fake_wr,
            )

    def test_falha_quando_so_existem_particoes_sem_filmes(self):
        fake_wr = MagicMock()
        fake_wr.s3.read_json.return_value = pd.DataFrame([
            {"year": "2024", "month": "01"}
        ])

        with self.assertRaises(ValueError):
            carregar_sor_json_para_tabela_sot(
                s3_bucket_sor="bucket-sor",
                s3_bucket_sot="bucket-sot",
                catalog_database="tmdb_dev",
                catalog_table="movies_sot",
                wr_module=fake_wr,
            )

        fake_wr.s3.to_parquet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
    