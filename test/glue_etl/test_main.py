"""Testes do modulo principal do Glue ETL."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Glue ETL main.py usa 'from src.utils import ...' sem pacote qualificado,
# portanto app/glue_etl precisa estar no sys.path durante o import.
_GLUE_ETL_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "app", "glue_etl"
)
_GLUE_ETL_DIR = os.path.abspath(_GLUE_ETL_DIR)


def _setup_mocks(resolved_args):
    """Adiciona mocks de awsglue e src.utils ao sys.modules."""
    mock_utils_mod = MagicMock()
    mock_utils_mod.getResolvedOptions.return_value = resolved_args
    sys.modules.setdefault("awsglue", MagicMock())
    sys.modules["awsglue.utils"] = mock_utils_mod

    mock_src_utils = MagicMock()
    sys.modules["src"] = MagicMock(utils=mock_src_utils)
    sys.modules["src.utils"] = mock_src_utils
    return mock_src_utils


def _reload_main():
    sys.modules.pop("app.glue_etl.main", None)
    if _GLUE_ETL_DIR not in sys.path:
        sys.path.insert(0, _GLUE_ETL_DIR)
    import app.glue_etl.main  # noqa: F401


class TestGlueEtlMain(unittest.TestCase):
    def test_chama_glue_data_quality_com_partitions(self):
        mock_src_utils = _setup_mocks(self._DEFAULT_ARGS)
        mock_src_utils.processar_tmdb.return_value = {"linhas_processadas": 10}
        # Mock direto na sys.modules
        mock_src_utils.chamar_glue_data_quality.return_value = {"job_name": "glue-data-quality-dev", "job_run_id": "123"}

        _reload_main()

        mock_src_utils.chamar_glue_data_quality.assert_called_with('glue-data-quality-dev', partition_cols='year,month')
    _DEFAULT_ARGS = {
        "GLUE_CATALOG_DATABASE": "tmdb_dev",
        "GLUE_CATALOG_TABLE": "movies_sot",
        "S3_BUCKET_SOR": "bucket-sor",
        "S3_BUCKET_SOT": "bucket-sot",
        "GLUE_DATA_QUALITY_JOB_NAME": "glue-data-quality-dev",
        "GLUE_CATALOG_TABLES": "tb_movies_tmdb,tb_tv_tmdb,tb_genre_movie_tmdb,tb_genre_tv_tmdb"
    }

    def tearDown(self):
        sys.modules.pop("app.glue_etl.main", None)
        for key in [k for k in sys.modules if k.startswith("awsglue")]:
            del sys.modules[key]
        for key in ["src", "src.utils"]:
            sys.modules.pop(key, None)
        if _GLUE_ETL_DIR in sys.path:
            sys.path.remove(_GLUE_ETL_DIR)

    def test_chama_processar_tmdb_com_argumentos_corretos(self):
        mock_src_utils = _setup_mocks(self._DEFAULT_ARGS)
        mock_src_utils.processar_tmdb.return_value = {"linhas_processadas": 10}

        _reload_main()

        expected_calls = [
            dict(input_path='s3://bucket-sor/', output_path='s3://bucket-sot/', database='tmdb_dev', table='tb_movies_tmdb', partitions_cols=['year', 'month'], partition_date_col='release_date'),
            dict(input_path='s3://bucket-sor/', output_path='s3://bucket-sot/', database='tmdb_dev', table='tb_tv_tmdb', partitions_cols=['year', 'month'], partition_date_col='first_air_date'),
            dict(input_path='s3://bucket-sor/', output_path='s3://bucket-sot/', database='tmdb_dev', table='tb_genre_movie_tmdb', partitions_cols=None, partition_date_col=None),
            dict(input_path='s3://bucket-sor/', output_path='s3://bucket-sot/', database='tmdb_dev', table='tb_genre_tv_tmdb', partitions_cols=None, partition_date_col=None),
        ]
        actual_calls = [call.kwargs for call in mock_src_utils.processar_tmdb.call_args_list]
        self.assertEqual(actual_calls, expected_calls)

    def test_main_executa_sem_excecao(self):
        mock_src_utils = _setup_mocks(self._DEFAULT_ARGS)
        mock_src_utils.processar_tmdb.return_value = {"linhas_processadas": 5}

        try:
            _reload_main()
        except Exception as exc:
            self.fail(f"main.py levantou excecao inesperada: {exc}")


if __name__ == "__main__":
    unittest.main()
