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
os.environ.setdefault("TMDB_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123:secret:tmdb-test")
os.environ.setdefault("GLUE_ETL_JOB_NAME", "test-glue-etl-job")
os.environ.setdefault("S3_BUCKET_SOR", "test-bucket-sor")

import main  # noqa: E402  (importação após configuração de env vars)


# ---------------------------------------------------------------------------
# Eventos simulados do EventBridge — espelham o que o Terraform configura
# ---------------------------------------------------------------------------

EVENTO_MOVIE = {
    "type": "movie",
    "database": "tmdb_db",
    "table_discover_movie": "discover_movie",
    "table_genre_movie": "genre_movie",
    "table_configuration_languages": "configuration_languages",
}

EVENTO_TV = {
    "type": "tv",
    "database": "tmdb_db",
    "table_discover_tv": "discover_tv",
    "table_genre_tv": "genre_tv",
    "table_configuration_countries": "configuration_countries",
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
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_retorna_status_200_para_movie(
        self, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"

        resposta = main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        self.assertEqual(resposta["statusCode"], 200)
        self.assertIn("movie", resposta["body"])

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_retorna_status_200_para_tv(
        self, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"

        resposta = main.lambda_handler(EVENTO_TV, self.mock_context)

        self.assertEqual(resposta["statusCode"], 200)
        self.assertIn("tv", resposta["body"])

    # --- Secrets Manager ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_busca_api_key_uma_unica_vez(
        self, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # Independente de quantos anos existam, o Secrets Manager é chamado só 1 vez
        mock_get_key.assert_called_once_with(main.TMDB_SECRET_ARN)

    # --- collect_reference_data ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_collect_reference_data_chamado_com_tipo_movie(
        self, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        mock_collect_ref.assert_called_once()
        # 4º argumento posicional é o content_type
        _, _, _, content_type = mock_collect_ref.call_args[0]
        self.assertEqual(content_type, "movie")

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    def test_collect_reference_data_chamado_com_tipo_tv(
        self, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"

        main.lambda_handler(EVENTO_TV, self.mock_context)

        _, _, _, content_type = mock_collect_ref.call_args[0]
        self.assertEqual(content_type, "tv")

    # --- Loop de anos ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_loop_executa_para_cada_ano(
        self, mock_dt, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2002  # Simula ano atual = 2002

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # START_YEAR=2000 até 2002 = 3 anos → 3 chamadas ao collect_and_save
        self.assertEqual(mock_collect.call_count, 3)
        # 3 chamadas no loop (com year) + 1 para referências (sem year) = 4 total
        self.assertEqual(mock_trigger.call_count, 4)

    # --- collect_and_save ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_collect_and_save_usa_folder_correto_para_movie(
        self, mock_dt, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2000  # 1 único ano para simplificar

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        kwargs = mock_collect.call_args[1]
        self.assertEqual(kwargs["folder"], "tmdb/discover/movie")
        self.assertEqual(kwargs["content_type"], "movie")

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_collect_and_save_usa_folder_correto_para_tv(
        self, mock_dt, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2000

        main.lambda_handler(EVENTO_TV, self.mock_context)

        kwargs = mock_collect.call_args[1]
        self.assertEqual(kwargs["folder"], "tmdb/discover/tv")
        self.assertEqual(kwargs["content_type"], "tv")

    # --- trigger_glue_job ---

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_glue_recebe_argumentos_padronizados(
        self, mock_dt, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2000  # 1 único ano

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # O 3º argumento posicional do trigger_glue_job é o glue_catalog_args
        _, _, catalog_args, _ = mock_trigger.call_args[0]

        # Os argumentos devem usar as chaves padronizadas (iguais para movie e tv)
        self.assertEqual(catalog_args["MEDIA_TYPE"], "movie")
        self.assertEqual(catalog_args["DATABASE"], "tmdb_db")
        self.assertEqual(catalog_args["DISCOVER_TABLE"], "discover_movie")
        self.assertEqual(catalog_args["GENRE_TABLE"], "genre_movie")
        self.assertEqual(catalog_args["CONFIGURATION_TABLE"], "configuration_languages")

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_glue_acionado_uma_vez_para_tabelas_de_referencia(
        self, mock_dt, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        """O Glue deve ser chamado sem year para as tabelas de gênero e configuração."""
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2000  # 1 ano no loop

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # 1 chamada sem year (referências) + 1 com year (loop) = 2 no total
        self.assertEqual(mock_trigger.call_count, 2)

        # A primeira chamada deve ser sem year (para as referências)
        primeira_chamada = mock_trigger.call_args_list[0]
        # call_args_list[0] é a chamada para referências: sem year
        # A assinatura é trigger_glue_job(glue_client, job_name, glue_catalog_args, year)
        # Sem year significa que o argumento year não foi passado (usa o padrão None)
        args_pos, kwargs = primeira_chamada
        # Pode vir como keyword ou como ausente (default)
        year_passado = kwargs.get("year", args_pos[3] if len(args_pos) > 3 else None)
        self.assertIsNone(year_passado)

    @patch("main.trigger_glue_job")
    @patch("main.collect_and_save")
    @patch("main.collect_reference_data")
    @patch("main.get_tmdb_api_key")
    @patch("main.boto3")
    @patch("main.datetime")
    def test_glue_no_loop_recebe_year_correto(
        self, mock_dt, mock_boto3, mock_get_key, mock_collect_ref, mock_collect, mock_trigger
    ):
        """As chamadas do Glue dentro do loop devem receber o year de cada iteração."""
        mock_get_key.return_value = "api-key-teste"
        mock_dt.now.return_value.year = 2001  # 2 anos: 2000 e 2001

        main.lambda_handler(EVENTO_MOVIE, self.mock_context)

        # As chamadas do loop são as 2 últimas (a primeira é a de referência)
        chamada_ano_2000 = mock_trigger.call_args_list[1]  # 2ª chamada
        chamada_ano_2001 = mock_trigger.call_args_list[2]  # 3ª chamada
        self.assertEqual(chamada_ano_2000[0][3], 2000)
        self.assertEqual(chamada_ano_2001[0][3], 2001)


if __name__ == "__main__":
    unittest.main()
