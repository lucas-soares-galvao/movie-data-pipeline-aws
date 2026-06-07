"""
test_utils.py — Testes unitários das funções auxiliares da Lambda.

Cada teste isola uma única função usando Mock, simulando as chamadas
externas (AWS, TMDB) sem fazer requisições reais.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.utils import (
    collect_configuration_data,
    collect_discover_data,
    collect_genre_data,
    fetch_tmdb_data,
    fetch_tmdb_reference,
    get_tmdb_api_key,
    save_to_s3,
    trigger_glue_job,
)


# ---------------------------------------------------------------------------
# get_tmdb_api_key
# ---------------------------------------------------------------------------


class TestGetTmdbApiKey(unittest.TestCase):
    @patch("src.utils.boto3")
    def test_retorna_chave_do_secrets_manager(self, mock_boto3):
        # Prepara o cliente simulado do Secrets Manager
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"tmdb_api_key": "chave-teste-123"})
        }

        resultado = get_tmdb_api_key("arn:aws:secretsmanager:us-east-1:123:secret:tmdb")

        self.assertEqual(resultado, "chave-teste-123")
        mock_boto3.client.assert_called_once_with("secretsmanager")
        mock_client.get_secret_value.assert_called_once_with(
            SecretId="arn:aws:secretsmanager:us-east-1:123:secret:tmdb"
        )


# ---------------------------------------------------------------------------
# fetch_tmdb_data
# ---------------------------------------------------------------------------


class TestFetchTmdbData(unittest.TestCase):
    def _mock_resposta(self, dados):
        """Cria um objeto de resposta HTTP simulado."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = dados
        return mock_resp

    @patch("src.utils.requests")
    def test_busca_filmes_com_url_correta(self, mock_requests):
        dados = {"page": 1, "results": [], "total_pages": 3, "total_results": 60}
        mock_requests.get.return_value = self._mock_resposta(dados)

        resultado = fetch_tmdb_data("minha-api-key", "movie", 2023, 1)

        url_chamada = mock_requests.get.call_args[0][0]
        self.assertIn("discover/movie", url_chamada)
        self.assertEqual(resultado, dados)

    @patch("src.utils.requests")
    def test_busca_series_com_url_correta(self, mock_requests):
        dados = {"page": 1, "results": [], "total_pages": 2, "total_results": 40}
        mock_requests.get.return_value = self._mock_resposta(dados)

        resultado = fetch_tmdb_data("minha-api-key", "tv", 2022, 1)

        url_chamada = mock_requests.get.call_args[0][0]
        self.assertIn("discover/tv", url_chamada)
        self.assertEqual(resultado, dados)

    @patch("src.utils.requests")
    def test_filme_usa_parametro_primary_release_year(self, mock_requests):
        mock_requests.get.return_value = self._mock_resposta(
            {"total_pages": 1, "results": []}
        )

        fetch_tmdb_data("key", "movie", 2020, 1)

        params = mock_requests.get.call_args[1]["params"]
        self.assertIn("primary_release_year", params)
        self.assertEqual(params["primary_release_year"], 2020)

    @patch("src.utils.requests")
    def test_serie_usa_parametro_first_air_date_year(self, mock_requests):
        mock_requests.get.return_value = self._mock_resposta(
            {"total_pages": 1, "results": []}
        )

        fetch_tmdb_data("key", "tv", 2020, 1)

        params = mock_requests.get.call_args[1]["params"]
        self.assertIn("first_air_date_year", params)
        self.assertEqual(params["first_air_date_year"], 2020)


# ---------------------------------------------------------------------------
# save_to_s3
# ---------------------------------------------------------------------------


class TestSaveToS3(unittest.TestCase):
    def test_salva_json_no_s3_com_parametros_corretos(self):
        mock_s3 = MagicMock()
        dados = {"id": 1, "titulo": "Filme Teste"}

        save_to_s3(
            mock_s3, "meu-bucket", dados, "tmdb/discover/movie/ano=2023/pagina_001.json"
        )

        mock_s3.put_object.assert_called_once()
        kwargs = mock_s3.put_object.call_args[1]
        self.assertEqual(kwargs["Bucket"], "meu-bucket")
        self.assertEqual(kwargs["Key"], "tmdb/discover/movie/ano=2023/pagina_001.json")
        self.assertEqual(kwargs["ContentType"], "application/json")

    def test_conteudo_salvo_e_json_valido(self):
        mock_s3 = MagicMock()
        dados = {"id": 1, "titulo": "Filme Teste"}

        save_to_s3(
            mock_s3, "meu-bucket", dados, "tmdb/discover/movie/ano=2023/pagina_001.json"
        )

        kwargs = mock_s3.put_object.call_args[1]
        # Decodifica o corpo e verifica que os dados foram preservados
        corpo = json.loads(kwargs["Body"].decode("utf-8"))
        self.assertEqual(corpo["id"], 1)
        self.assertEqual(corpo["titulo"], "Filme Teste")


# ---------------------------------------------------------------------------
# trigger_glue_job
# ---------------------------------------------------------------------------


class TestTriggerGlueJob(unittest.TestCase):
    def test_inicia_job_e_retorna_run_id(self):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr_abc123"}

        run_id = trigger_glue_job(
            mock_glue,
            "meu-glue-job",
            {"database": "tmdb_db"},
            table_type="discover",
            table_name="discover_movie",
            year=2023,
        )

        self.assertEqual(run_id, "jr_abc123")

    def test_argumentos_do_glue_contem_year_e_tabelas(self):
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr_xyz"}

        trigger_glue_job(
            mock_glue,
            "meu-glue-job",
            {"database": "tmdb_db"},
            table_type="discover",
            table_name="discover_movie",
            year=2023,
        )

        args_glue = mock_glue.start_job_run.call_args[1]["Arguments"]
        self.assertEqual(args_glue["--YEAR"], "2023")
        self.assertEqual(args_glue["--DATABASE"], "tmdb_db")
        self.assertEqual(args_glue["--TABLE_TYPE"], "discover")
        self.assertEqual(args_glue["--TABLE_NAME"], "discover_movie")

    def test_sem_year_nao_inclui_argumento_year(self):
        """Quando chamado sem year, o Glue não recebe --YEAR (tabelas de referência)."""
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr_ref"}

        trigger_glue_job(
            mock_glue,
            "meu-glue-job",
            {"database": "tmdb_db"},
            table_type="genre",
            table_name="genre_movie",
        )

        args_glue = mock_glue.start_job_run.call_args[1]["Arguments"]
        self.assertNotIn("--YEAR", args_glue)
        self.assertEqual(args_glue["--DATABASE"], "tmdb_db")
        self.assertEqual(args_glue["--TABLE_TYPE"], "genre")
        self.assertEqual(args_glue["--TABLE_NAME"], "genre_movie")

    def test_table_type_incluido_nos_argumentos_do_glue(self):
        """table_type sempre é repassado ao Glue como --TABLE_TYPE."""
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr_tt"}

        trigger_glue_job(
            mock_glue,
            "meu-glue-job",
            {"database": "tmdb_db"},
            table_type="genre",
            table_name="genre_movie",
        )

        args_glue = mock_glue.start_job_run.call_args[1]["Arguments"]
        self.assertEqual(args_glue["--TABLE_TYPE"], "genre")
        self.assertNotIn("--YEAR", args_glue)

    def test_table_name_incluido_nos_argumentos_do_glue(self):
        """table_name sempre é repassado ao Glue como --TABLE_NAME."""
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr_tn"}

        trigger_glue_job(
            mock_glue,
            "meu-glue-job",
            {"database": "tmdb_db"},
            table_type="genre",
            table_name="genre_movie",
        )

        args_glue = mock_glue.start_job_run.call_args[1]["Arguments"]
        self.assertEqual(args_glue["--TABLE_NAME"], "genre_movie")
        self.assertNotIn("--YEAR", args_glue)


# ---------------------------------------------------------------------------
# fetch_tmdb_reference
# ---------------------------------------------------------------------------


class TestFetchTmdbReference(unittest.TestCase):
    @patch("src.utils.requests")
    def test_busca_endpoint_sem_params_extras(self, mock_requests):
        dados = [{"iso_639_1": "pt", "english_name": "Portuguese"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = dados
        mock_requests.get.return_value = mock_resp

        resultado = fetch_tmdb_reference("minha-key", "/configuration/languages")

        url_chamada = mock_requests.get.call_args[0][0]
        self.assertIn("/configuration/languages", url_chamada)
        self.assertEqual(resultado, dados)

    @patch("src.utils.requests")
    def test_busca_endpoint_com_params_extras(self, mock_requests):
        dados = {"genres": [{"id": 28, "name": "Ação"}]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = dados
        mock_requests.get.return_value = mock_resp

        resultado = fetch_tmdb_reference(
            "minha-key", "/genre/movie/list", {"language": "pt-BR"}
        )

        params = mock_requests.get.call_args[1]["params"]
        self.assertEqual(params["language"], "pt-BR")
        self.assertEqual(resultado, dados)


# ---------------------------------------------------------------------------
# collect_genre_data
# ---------------------------------------------------------------------------


class TestCollectGenreData(unittest.TestCase):
    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_movie_coleta_generos_de_filmes(self, mock_fetch, mock_save):
        generos = [{"id": 28, "name": "Ação"}]
        mock_fetch.return_value = {"genres": generos}
        mock_s3 = MagicMock()

        collect_genre_data("key", mock_s3, "meu-bucket", "movie")

        mock_fetch.assert_called_once()
        endpoint = mock_fetch.call_args[0][1]
        self.assertEqual(endpoint, "/genre/movie/list")
        dados_salvos = mock_save.call_args[0][2]
        self.assertEqual(dados_salvos, generos)
        s3_key = mock_save.call_args[0][3]
        self.assertEqual(s3_key, "tmdb/genre/movie/generos_filmes.json")

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_tv_coleta_generos_de_series(self, mock_fetch, mock_save):
        generos = [{"id": 10759, "name": "Ação & Aventura"}]
        mock_fetch.return_value = {"genres": generos}
        mock_s3 = MagicMock()

        collect_genre_data("key", mock_s3, "meu-bucket", "tv")

        mock_fetch.assert_called_once()
        endpoint = mock_fetch.call_args[0][1]
        self.assertEqual(endpoint, "/genre/tv/list")
        dados_salvos = mock_save.call_args[0][2]
        self.assertEqual(dados_salvos, generos)
        s3_key = mock_save.call_args[0][3]
        self.assertEqual(s3_key, "tmdb/genre/tv/generos_series.json")

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_movie_nao_coleta_dados_de_tv(self, mock_fetch, mock_save):
        mock_fetch.return_value = {"genres": []}
        mock_s3 = MagicMock()

        collect_genre_data("key", mock_s3, "meu-bucket", "movie")

        endpoints = [c[0][1] for c in mock_fetch.call_args_list]
        self.assertNotIn("/genre/tv/list", endpoints)


# ---------------------------------------------------------------------------
# collect_configuration_data
# ---------------------------------------------------------------------------


class TestCollectConfigurationData(unittest.TestCase):
    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_movie_coleta_idiomas(self, mock_fetch, mock_save):
        mock_fetch.return_value = []
        mock_s3 = MagicMock()

        collect_configuration_data("key", mock_s3, "meu-bucket", "movie")

        mock_fetch.assert_called_once()
        endpoint = mock_fetch.call_args[0][1]
        self.assertEqual(endpoint, "/configuration/languages")
        s3_key = mock_save.call_args[0][3]
        self.assertEqual(s3_key, "tmdb/configuration/languages/idiomas.json")

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_tv_coleta_paises(self, mock_fetch, mock_save):
        mock_fetch.return_value = []
        mock_s3 = MagicMock()

        collect_configuration_data("key", mock_s3, "meu-bucket", "tv")

        mock_fetch.assert_called_once()
        endpoint = mock_fetch.call_args[0][1]
        self.assertEqual(endpoint, "/configuration/countries")
        s3_key = mock_save.call_args[0][3]
        self.assertEqual(s3_key, "tmdb/configuration/countries/paises.json")


# ---------------------------------------------------------------------------
# collect_and_save
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# collect_discover_data
# ---------------------------------------------------------------------------


class TestCollectDiscoverData(unittest.TestCase):
    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_data")
    def test_salva_todas_as_paginas_disponiveis(self, mock_fetch, mock_save):
        # TMDB retorna 3 páginas disponíveis no total
        mock_fetch.return_value = {"page": 1, "results": [], "total_pages": 3}
        mock_s3 = MagicMock()

        collect_discover_data(
            "key", mock_s3, "meu-bucket", "movie", "tmdb/discover/movie", 2023
        )

        # 3 páginas salvas + 1 chamada extra para detectar o fim = 4 chamadas ao fetch
        self.assertEqual(mock_fetch.call_count, 4)
        self.assertEqual(mock_save.call_count, 3)

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_data")
    def test_para_quando_so_ha_uma_pagina(self, mock_fetch, mock_save):
        # Apenas 1 página disponível
        mock_fetch.return_value = {"page": 1, "results": [], "total_pages": 1}
        mock_s3 = MagicMock()

        collect_discover_data(
            "key", mock_s3, "meu-bucket", "tv", "tmdb/discover/tv", 2010
        )

        # 1 página salva + 1 chamada extra para detectar o fim = 2 chamadas ao fetch
        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(mock_save.call_count, 1)

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_data")
    def test_s3_key_tem_formato_correto(self, mock_fetch, mock_save):
        mock_fetch.return_value = {"page": 1, "results": [], "total_pages": 1}
        mock_s3 = MagicMock()

        collect_discover_data(
            "key", mock_s3, "meu-bucket", "movie", "tmdb/discover/movie", 2023
        )

        # Verifica o caminho do arquivo salvo na primeira (e única) página
        s3_key_usado = mock_save.call_args[0][3]
        self.assertEqual(s3_key_usado, "tmdb/discover/movie/ano=2023/pagina_001.json")

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_data")
    def test_salva_apenas_results_sem_metadados_de_paginacao(
        self, mock_fetch, mock_save
    ):
        filmes = [{"id": 1, "title": "Filme A"}, {"id": 2, "title": "Filme B"}]
        mock_fetch.return_value = {
            "page": 1,
            "results": filmes,
            "total_pages": 1,
            "total_results": 2,
        }
        mock_s3 = MagicMock()

        collect_discover_data(
            "key", mock_s3, "meu-bucket", "movie", "tmdb/discover/movie", 2023
        )

        # O 3º argumento posicional de save_to_s3 é o dado salvo
        dado_salvo = mock_save.call_args[0][2]
        # Deve ser a lista bruta de filmes sem metadados de paginação
        # (enriquecimento com runtime é responsabilidade do Glue ETL)
        ids_salvos = [item["id"] for item in dado_salvo]
        self.assertEqual(ids_salvos, [1, 2])
        self.assertNotIn("page", dado_salvo)
        self.assertNotIn("total_pages", dado_salvo)


if __name__ == "__main__":
    unittest.main()
