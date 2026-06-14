import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from src.utils import (
    _tmdb_get,
    collect_configuration_data,
    collect_discover_data,
    collect_genre_data,
    collect_now_playing_data,
    collect_watch_providers_ref,
    fetch_tmdb_data,
    fetch_tmdb_reference,
    get_tmdb_api_key,
    save_to_s3,
    trigger_glue_job,
)


# ---------------------------------------------------------------------------
# _tmdb_get
# ---------------------------------------------------------------------------


class TestTmdbGet(unittest.TestCase):
    def _make_response(self, status_code=200, json_data=None, headers=None):
        r = MagicMock()
        r.status_code = status_code
        r.json.return_value = json_data if json_data is not None else {}
        r.headers = headers or {}
        r.raise_for_status.return_value = None
        return r

    @patch("src.utils.time.sleep")
    @patch("src.utils.requests.get")
    def test_retorna_json_em_sucesso(self, mock_get, mock_sleep):
        mock_get.return_value = self._make_response(200, {"ok": True})
        resultado = _tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        self.assertEqual(resultado, {"ok": True})
        mock_sleep.assert_not_called()

    @patch("src.utils.time.sleep")
    @patch("src.utils.requests.get")
    def test_retry_em_status_transiente_e_retorna_em_sucesso(self, mock_get, mock_sleep):
        mock_get.side_effect = [self._make_response(500), self._make_response(200, {"ok": True})]
        resultado = _tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        self.assertEqual(resultado, {"ok": True})
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("src.utils.time.sleep")
    @patch("src.utils.requests.get")
    def test_retry_em_429_usa_retry_after(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            self._make_response(429, headers={"Retry-After": "5"}),
            self._make_response(200, {}),
        ]
        _tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        wait = mock_sleep.call_args[0][0]
        self.assertGreaterEqual(wait, 5)

    @patch("src.utils.time.sleep")
    @patch("src.utils.requests.get")
    def test_retry_em_connection_error_e_retorna_em_sucesso(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("timeout"),
            self._make_response(200, {"ok": True}),
        ]
        resultado = _tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        self.assertEqual(resultado, {"ok": True})
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("src.utils.time.sleep")
    @patch("src.utils.requests.get")
    def test_levanta_apos_esgotar_tentativas_http(self, mock_get, mock_sleep):
        r500 = self._make_response(500)
        r500.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        mock_get.return_value = r500
        with self.assertRaises(requests.exceptions.HTTPError):
            _tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        self.assertEqual(mock_get.call_count, 3)

    @patch("src.utils.time.sleep")
    @patch("src.utils.requests.get")
    def test_levanta_apos_esgotar_tentativas_connection(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.exceptions.ConnectionError("fail")
        with self.assertRaises(requests.exceptions.ConnectionError):
            _tmdb_get("https://api.themoviedb.org/3/test", {"api_key": "k"})
        self.assertEqual(mock_get.call_count, 3)


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

    def test_discover_inclui_end_year(self):
        """Chamadas de discover repassam END_YEAR ao Glue."""
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr_sy"}

        trigger_glue_job(
            mock_glue,
            "meu-glue-job",
            {"database": "tmdb_db"},
            table_type="discover",
            table_name="discover_movie",
            year=2025,
            end_year=2026,
        )

        args_glue = mock_glue.start_job_run.call_args[1]["Arguments"]
        self.assertEqual(args_glue["--END_YEAR"], "2026")

    def test_genre_nao_inclui_end_year(self):
        """Chamadas de genre/configuration não recebem END_YEAR."""
        mock_glue = MagicMock()
        mock_glue.start_job_run.return_value = {"JobRunId": "jr_no_sy"}

        trigger_glue_job(
            mock_glue,
            "meu-glue-job",
            {"database": "tmdb_db"},
            table_type="genre",
            table_name="genre_movie",
        )

        args_glue = mock_glue.start_job_run.call_args[1]["Arguments"]
        self.assertNotIn("--END_YEAR", args_glue)


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


# ---------------------------------------------------------------------------
# collect_now_playing_data
# ---------------------------------------------------------------------------


class TestCollectNowPlayingData(unittest.TestCase):
    def _page_response(self, page, total_pages, results=None, dates=None):
        return {
            "page": page,
            "total_pages": total_pages,
            "results": results if results is not None else [{"id": page * 10, "title": f"Filme {page}"}],
            "dates": dates if dates is not None else {"minimum": "2025-01-01", "maximum": "2025-01-14"},
        }

    @patch("src.utils.save_to_s3")
    @patch("src.utils._tmdb_get")
    def test_pagina_unica_enriquece_com_datas_teatrais(self, mock_get, mock_save):
        mock_get.side_effect = [
            self._page_response(1, 1, [{"id": 1, "title": "Filme X"}], {"minimum": "2025-01-01", "maximum": "2025-01-14"}),
            self._page_response(2, 1),  # page > total_pages → break
        ]
        mock_s3 = MagicMock()

        collect_now_playing_data("api-key", mock_s3, "meu-bucket")

        dados_salvos = mock_save.call_args[0][2]
        self.assertEqual(len(dados_salvos), 1)
        self.assertEqual(dados_salvos[0]["theater_start_date"], "2025-01-01")
        self.assertEqual(dados_salvos[0]["theater_end_date"], "2025-01-14")

    @patch("src.utils.save_to_s3")
    @patch("src.utils._tmdb_get")
    def test_multiplas_paginas_salva_cada_uma(self, mock_get, mock_save):
        mock_get.side_effect = [
            self._page_response(1, 3),
            self._page_response(2, 3),
            self._page_response(3, 3),
            self._page_response(4, 3),  # page > total_pages → break
        ]
        mock_s3 = MagicMock()

        collect_now_playing_data("api-key", mock_s3, "meu-bucket")

        self.assertEqual(mock_save.call_count, 3)

    @patch("src.utils.save_to_s3")
    @patch("src.utils._tmdb_get")
    def test_para_quando_page_maior_que_total_pages(self, mock_get, mock_save):
        mock_get.side_effect = [
            self._page_response(1, 1),
            self._page_response(2, 1),  # page > total_pages → break
        ]
        mock_s3 = MagicMock()

        collect_now_playing_data("api-key", mock_s3, "meu-bucket")

        self.assertEqual(mock_save.call_count, 1)

    @patch("src.utils.save_to_s3")
    @patch("src.utils._tmdb_get")
    def test_s3_key_tem_formato_correto(self, mock_get, mock_save):
        mock_get.side_effect = [
            self._page_response(1, 1),
            self._page_response(2, 1),  # break
        ]
        mock_s3 = MagicMock()

        collect_now_playing_data("api-key", mock_s3, "meu-bucket")

        s3_key = mock_save.call_args[0][3]
        self.assertEqual(s3_key, "tmdb/now_playing/movie/pagina_001.json")


# ---------------------------------------------------------------------------
# collect_watch_providers_ref
# ---------------------------------------------------------------------------


class TestCollectWatchProvidersRef(unittest.TestCase):
    def _api_response(self, results):
        return {"results": results}

    def _provider(self, pid, name, logo, priority_br):
        return {
            "provider_id": pid,
            "provider_name": name,
            "logo_path": logo,
            "display_priorities": {"BR": priority_br},
        }

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_movie_chama_endpoint_correto(self, mock_fetch, mock_save):
        mock_fetch.return_value = self._api_response([])
        mock_s3 = MagicMock()

        collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        endpoint = mock_fetch.call_args[0][1]
        self.assertEqual(endpoint, "/watch/providers/movie")

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_tv_chama_endpoint_correto(self, mock_fetch, mock_save):
        mock_fetch.return_value = self._api_response([])
        mock_s3 = MagicMock()

        collect_watch_providers_ref("key", mock_s3, "meu-bucket", "tv")

        endpoint = mock_fetch.call_args[0][1]
        self.assertEqual(endpoint, "/watch/providers/tv")

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_envia_watch_region_br(self, mock_fetch, mock_save):
        mock_fetch.return_value = self._api_response([])
        mock_s3 = MagicMock()

        collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        params = mock_fetch.call_args[0][2]
        self.assertEqual(params, {"watch_region": "BR"})

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_s3_key_movie(self, mock_fetch, mock_save):
        mock_fetch.return_value = self._api_response([])
        mock_s3 = MagicMock()

        collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        s3_key = mock_save.call_args[0][3]
        self.assertEqual(s3_key, "tmdb/watch_providers_ref/movie/watch_providers_ref.json")

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_s3_key_tv(self, mock_fetch, mock_save):
        mock_fetch.return_value = self._api_response([])
        mock_s3 = MagicMock()

        collect_watch_providers_ref("key", mock_s3, "meu-bucket", "tv")

        s3_key = mock_save.call_args[0][3]
        self.assertEqual(s3_key, "tmdb/watch_providers_ref/tv/watch_providers_ref.json")

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_extrai_campos_corretos_do_provider(self, mock_fetch, mock_save):
        provider = self._provider(8, "Netflix", "/netflix.png", 1)
        mock_fetch.return_value = self._api_response([provider])
        mock_s3 = MagicMock()

        collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        dados_salvos = mock_save.call_args[0][2]
        self.assertEqual(len(dados_salvos), 1)
        self.assertEqual(dados_salvos[0]["provider_id"], 8)
        self.assertEqual(dados_salvos[0]["provider_name"], "Netflix")
        self.assertEqual(dados_salvos[0]["logo_path"], "/netflix.png")
        self.assertEqual(dados_salvos[0]["display_priority_br"], 1)

    @patch("src.utils.save_to_s3")
    @patch("src.utils.fetch_tmdb_reference")
    def test_display_priority_br_none_quando_ausente(self, mock_fetch, mock_save):
        provider = {"provider_id": 9, "provider_name": "Prime", "logo_path": None}
        mock_fetch.return_value = self._api_response([provider])
        mock_s3 = MagicMock()

        collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        dados_salvos = mock_save.call_args[0][2]
        self.assertIsNone(dados_salvos[0]["display_priority_br"])


if __name__ == "__main__":
    unittest.main()
