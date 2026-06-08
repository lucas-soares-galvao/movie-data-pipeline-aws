"""
test_main.py — Testes unitários do handler principal da Lambda.

As funções auxiliares (collect_and_save, trigger_glue_job, etc.) já foram
testadas em test_utils.py. Aqui testamos apenas a lógica de orquestração
do lambda_handler: se ele chama as funções certas, com os argumentos certos,
na ordem certa.

Os decoradores @patch substituem as dependências externas por objetos simulados
(Mocks), sem chamar AWS ou TMDB de verdade.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

# As variáveis de ambiente precisam existir ANTES de importar main,
# pois main.py as lê no momento em que é carregado pelo Python.
os.environ.setdefault(
    "TMDB_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123:secret:tmdb-test"
)
os.environ.setdefault("GLUE_ETL_JOB_NAME", "test-glue-etl-job")
os.environ.setdefault("S3_BUCKET_SOR", "test-bucket-sor")

import main  # noqa: E402  (importação após configuração de env vars)


# ---------------------------------------------------------------------------
# Eventos simulados do EventBridge — espelham o que o Terraform configura
# ---------------------------------------------------------------------------

EVENTO_MOVIE = {
    "type": "movie",
    "database": "tmdb_db",
    "database_unified": "tmdb_unified_db",
    "table_discover_movie": "discover_movie",
    "table_genre_movie": "genre_movie",
    "table_configuration_languages": "configuration_languages",
    "table_watch_providers_ref_movie": "watch_providers_ref_movie",
}

EVENTO_TV = {
    "type": "tv",
    "database": "tmdb_db",
    "database_unified": "tmdb_unified_db",
    "table_discover_tv": "discover_tv",
    "table_genre_tv": "genre_tv",
    "table_configuration_countries": "configuration_countries",
    "table_watch_providers_ref_tv": "watch_providers_ref_tv",
}


# ---------------------------------------------------------------------------
# Testes do lambda_handler
# ---------------------------------------------------------------------------


class TestLambdaHandler(unittest.TestCase):
    def setUp(self):
        """Objeto de contexto simulado (exigido pela assinatura do handler)."""
        self.mock_context = MagicMock()

    # --- Resposta HTTP ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_retorna_status_200_para_movie(
        self,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"

        resposta = main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        self.assertEqual(resposta["statusCode"], 200)
        self.assertIn("movie", resposta["body"])

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_retorna_status_200_para_tv(
        self,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"

        resposta = main.lambda_handler(EVENTO_TV, self.mock_context)

        self.assertEqual(resposta["statusCode"], 200)
        self.assertIn("tv", resposta["body"])

    # --- Secrets Manager ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_busca_api_key_uma_unica_vez(
        self,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # Independente de quantos anos existam, o Secrets Manager é chamado só 1 vez
        mock_get_key.assert_called_once_with(main.TMDB_SECRET_ARN)

    # --- collect_genre_data e collect_configuration_data ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_collect_genre_chamado_com_tipo_movie(
        self,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        mock_genre.assert_called_once()
        _, _, _, content_type = mock_genre.call_args[0]
        self.assertEqual(content_type, "movie")

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_collect_configuration_chamado_com_tipo_tv(
        self,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"

        main.lambda_handler(EVENTO_TV, self.mock_context)

        mock_config.assert_called_once()
        _, _, _, content_type = mock_config.call_args[0]
        self.assertEqual(content_type, "tv")

    # --- Loop de anos ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_loop_executa_para_cada_ano(
        self,
        mock_dt,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2027  # Simula ano atual = 2027

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # start_year = 2027 - 1 = 2026 → range(2026, 2028) = 2 anos
        self.assertEqual(mock_discover.call_count, 2)
        # genre(1) + configuration(1) + watch_providers_ref(1) + 2xdiscover = 5
        self.assertEqual(mock_trigger.call_count, 5)

    # --- collect_discover_data ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_collect_discover_usa_folder_correto_para_movie(
        self,
        mock_dt,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2025  # 1 único ano para simplificar

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        kwargs = mock_discover.call_args[1]
        self.assertEqual(kwargs["folder"], "tmdb/discover/movie")
        self.assertEqual(kwargs["content_type"], "movie")

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_collect_discover_usa_folder_correto_para_tv(
        self,
        mock_dt,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2025

        main.lambda_handler(EVENTO_TV, self.mock_context)

        kwargs = mock_discover.call_args[1]
        self.assertEqual(kwargs["folder"], "tmdb/discover/tv")
        self.assertEqual(kwargs["content_type"], "tv")

    # --- trigger_glue_job ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_glue_recebe_argumentos_padronizados(
        self,
        mock_dt,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2025  # 1 único ano

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # Verifica os args base e table_name de cada chamada ao Glue
        chamada_genre = mock_trigger.call_args_list[0]
        chamada_config = mock_trigger.call_args_list[1]
        chamada_watch_ref = mock_trigger.call_args_list[2]
        chamada_disc = mock_trigger.call_args_list[3]

        # genre e discover usam o database do media type; configuration usa o unificado
        for chamada in (chamada_genre, chamada_disc):
            args_base = chamada[0][2]
            self.assertEqual(args_base["MEDIA_TYPE"], "movie")
            self.assertEqual(args_base["DATABASE"], "tmdb_db")

        args_config = chamada_config[0][2]
        self.assertEqual(args_config["MEDIA_TYPE"], "movie")
        self.assertEqual(args_config["DATABASE"], "tmdb_unified_db")

        args_watch_ref = chamada_watch_ref[0][2]
        self.assertEqual(args_watch_ref["MEDIA_TYPE"], "movie")
        self.assertEqual(args_watch_ref["DATABASE"], "tmdb_db")

        # table_name varia conforme o contexto (keyword arg)
        self.assertEqual(chamada_genre[1].get("table_name"), "genre_movie")
        self.assertEqual(chamada_config[1].get("table_name"), "configuration_languages")
        self.assertEqual(chamada_watch_ref[1].get("table_name"), "watch_providers_ref_movie")
        self.assertEqual(chamada_disc[1].get("table_name"), "discover_movie")

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_glue_acionado_para_genre_e_configuration_sem_year(
        self,
        mock_dt,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        """As chamadas do Glue para genre e configuration não devem receber year."""
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2025  # 1 ano no loop

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # genre(1) + configuration(1) + watch_providers_ref(1) + discover(2) = 5
        # start_year = 2025 - 1 = 2024 -> range(2024, 2026) = [2024, 2025]
        self.assertEqual(mock_trigger.call_count, 5)

        # 1ª chamada: genre — sem year, table_type="genre"
        chamada_genre = mock_trigger.call_args_list[0]
        self.assertIsNone(chamada_genre[1].get("year"))
        self.assertEqual(chamada_genre[1].get("table_type"), "genre")

        # 2ª chamada: configuration — sem year, table_type="configuration"
        chamada_config = mock_trigger.call_args_list[1]
        self.assertIsNone(chamada_config[1].get("year"))
        self.assertEqual(chamada_config[1].get("table_type"), "configuration")

        # 3a chamada: watch_providers_ref — sem year, table_type="watch_providers_ref"
        chamada_watch_ref = mock_trigger.call_args_list[2]
        self.assertIsNone(chamada_watch_ref[1].get("year"))
        self.assertEqual(chamada_watch_ref[1].get("table_type"), "watch_providers_ref")

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_glue_no_loop_recebe_year_e_table_type_corretos(
        self,
        mock_dt,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        """As chamadas do Glue dentro do loop devem receber year e table_type='discover'."""
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2026  # 2 anos: 2025 e 2026

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # genre(0) + configuration(1) + watch_providers_ref(2) + discover_2025(3) + discover_2026(4)
        chamada_ano_2025 = mock_trigger.call_args_list[3]
        chamada_ano_2026 = mock_trigger.call_args_list[4]

        self.assertEqual(chamada_ano_2025[1].get("year"), 2025)
        self.assertEqual(chamada_ano_2025[1].get("table_type"), "discover")
        self.assertEqual(chamada_ano_2026[1].get("year"), 2026)
        self.assertEqual(chamada_ano_2026[1].get("table_type"), "discover")

    @patch("main.trigger_glue_job")
    @patch("main.collect_discover_data")
    @patch("main.collect_watch_providers_ref")
    @patch("main.collect_configuration_data")
    @patch("main.collect_genre_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_glue_discover_recebe_start_year_e_end_year(
        self,
        mock_dt,
        mock_boto3,
        mock_get_key,
        mock_genre,
        mock_config,
        mock_watch_ref,
        mock_discover,
        mock_trigger,
    ):
        """Todas as chamadas de discover repassam start_year e end_year."""
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2026  # start=2025, end=2026

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # genre(0) + configuration(1) + watch_providers_ref(2) + discover_2025(3) + discover_2026(4)
        for chamada in mock_trigger.call_args_list[3:]:
            self.assertEqual(chamada[1].get("start_year"), 2025)
            self.assertEqual(chamada[1].get("end_year"), 2026)


if __name__ == "__main__":
    unittest.main()
