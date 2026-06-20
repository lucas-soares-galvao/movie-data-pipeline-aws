import json
from unittest.mock import MagicMock, patch

from src.utils import (
    collect_configuration_data,
    collect_discover_data,
    collect_genre_data,
    collect_now_playing_data,
    collect_watch_providers_ref,
    fetch_tmdb_data,
    fetch_tmdb_reference,
    save_to_s3,
)


# ---------------------------------------------------------------------------
# fetch_tmdb_data
# ---------------------------------------------------------------------------


class TestFetchTmdbData:
    def test_busca_filmes_com_url_correta(self):
        dados = {"page": 1, "results": [], "total_pages": 3, "total_results": 60}
        with patch("src.utils.tmdb_get", return_value=dados) as mock_tmdb_get:
            resultado = fetch_tmdb_data("minha-api-key", "movie", 2023, 1)

        url_chamada = mock_tmdb_get.call_args[0][0]
        assert "discover/movie" in url_chamada
        assert resultado == dados

    def test_busca_series_com_url_correta(self):
        dados = {"page": 1, "results": [], "total_pages": 2, "total_results": 40}
        with patch("src.utils.tmdb_get", return_value=dados) as mock_tmdb_get:
            resultado = fetch_tmdb_data("minha-api-key", "tv", 2022, 1)

        url_chamada = mock_tmdb_get.call_args[0][0]
        assert "discover/tv" in url_chamada
        assert resultado == dados

    def test_filme_usa_parametro_primary_release_year(self):
        with patch("src.utils.tmdb_get", return_value={"total_pages": 1, "results": []}) as mock_tmdb_get:
            fetch_tmdb_data("key", "movie", 2020, 1)

        params = mock_tmdb_get.call_args[0][1]
        assert "primary_release_year" in params
        assert params["primary_release_year"] == 2020

    def test_serie_usa_parametro_first_air_date_year(self):
        with patch("src.utils.tmdb_get", return_value={"total_pages": 1, "results": []}) as mock_tmdb_get:
            fetch_tmdb_data("key", "tv", 2020, 1)

        params = mock_tmdb_get.call_args[0][1]
        assert "first_air_date_year" in params
        assert params["first_air_date_year"] == 2020


# ---------------------------------------------------------------------------
# save_to_s3
# ---------------------------------------------------------------------------


class TestSaveToS3:
    def test_salva_json_no_s3_com_parametros_corretos(self):
        mock_s3 = MagicMock()
        dados = {"id": 1, "titulo": "Filme Teste"}

        save_to_s3(
            mock_s3, "meu-bucket", dados, "tmdb/discover/movie/ano=2023/pagina_001.json"
        )

        mock_s3.put_object.assert_called_once()
        kwargs = mock_s3.put_object.call_args[1]
        assert kwargs["Bucket"] == "meu-bucket"
        assert kwargs["Key"] == "tmdb/discover/movie/ano=2023/pagina_001.json"
        assert kwargs["ContentType"] == "application/json"

    def test_conteudo_salvo_e_json_valido(self):
        mock_s3 = MagicMock()
        dados = {"id": 1, "titulo": "Filme Teste"}

        save_to_s3(
            mock_s3, "meu-bucket", dados, "tmdb/discover/movie/ano=2023/pagina_001.json"
        )

        kwargs = mock_s3.put_object.call_args[1]
        corpo = json.loads(kwargs["Body"].decode("utf-8"))
        assert corpo["id"] == 1
        assert corpo["titulo"] == "Filme Teste"


# ---------------------------------------------------------------------------
# fetch_tmdb_reference
# ---------------------------------------------------------------------------


class TestFetchTmdbReference:
    def test_busca_endpoint_sem_params_extras(self):
        dados = [{"iso_639_1": "pt", "english_name": "Portuguese"}]
        with patch("src.utils.tmdb_get", return_value=dados) as mock_tmdb_get:
            resultado = fetch_tmdb_reference("minha-key", "/configuration/languages")

        url_chamada = mock_tmdb_get.call_args[0][0]
        assert "/configuration/languages" in url_chamada
        assert resultado == dados

    def test_busca_endpoint_com_params_extras(self):
        dados = {"genres": [{"id": 28, "name": "Acao"}]}
        with patch("src.utils.tmdb_get", return_value=dados) as mock_tmdb_get:
            resultado = fetch_tmdb_reference(
                "minha-key", "/genre/movie/list", {"language": "pt-BR"}
            )

        params = mock_tmdb_get.call_args[0][1]
        assert params["language"] == "pt-BR"
        assert resultado == dados


# ---------------------------------------------------------------------------
# collect_genre_data
# ---------------------------------------------------------------------------


class TestCollectGenreData:
    def test_movie_coleta_generos_de_filmes(self):
        generos = [{"id": 28, "name": "Acao"}]
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value={"genres": generos}) as mock_fetch,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_genre_data("key", mock_s3, "meu-bucket", "movie")

        mock_fetch.assert_called_once()
        endpoint = mock_fetch.call_args[0][1]
        assert endpoint == "/genre/movie/list"
        dados_salvos = mock_save.call_args[0][2]
        assert dados_salvos == generos
        s3_key = mock_save.call_args[0][3]
        assert s3_key == "tmdb/genre/movie/generos_filmes.json"

    def test_tv_coleta_generos_de_series(self):
        generos = [{"id": 10759, "name": "Acao & Aventura"}]
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value={"genres": generos}) as mock_fetch,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_genre_data("key", mock_s3, "meu-bucket", "tv")

        mock_fetch.assert_called_once()
        endpoint = mock_fetch.call_args[0][1]
        assert endpoint == "/genre/tv/list"
        dados_salvos = mock_save.call_args[0][2]
        assert dados_salvos == generos
        s3_key = mock_save.call_args[0][3]
        assert s3_key == "tmdb/genre/tv/generos_series.json"

    def test_movie_nao_coleta_dados_de_tv(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value={"genres": []}) as mock_fetch,
            patch("src.utils.save_to_s3"),
        ):
            collect_genre_data("key", mock_s3, "meu-bucket", "movie")

        endpoints = [c[0][1] for c in mock_fetch.call_args_list]
        assert "/genre/tv/list" not in endpoints


# ---------------------------------------------------------------------------
# collect_configuration_data
# ---------------------------------------------------------------------------


class TestCollectConfigurationData:
    def test_movie_coleta_idiomas(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=[]) as mock_fetch,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_configuration_data("key", mock_s3, "meu-bucket", "movie")

        mock_fetch.assert_called_once()
        endpoint = mock_fetch.call_args[0][1]
        assert endpoint == "/configuration/languages"
        s3_key = mock_save.call_args[0][3]
        assert s3_key == "tmdb/configuration/languages/idiomas.json"

    def test_tv_coleta_paises(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=[]) as mock_fetch,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_configuration_data("key", mock_s3, "meu-bucket", "tv")

        mock_fetch.assert_called_once()
        endpoint = mock_fetch.call_args[0][1]
        assert endpoint == "/configuration/countries"
        s3_key = mock_save.call_args[0][3]
        assert s3_key == "tmdb/configuration/countries/paises.json"


# ---------------------------------------------------------------------------
# collect_discover_data
# ---------------------------------------------------------------------------


class TestCollectDiscoverData:
    def test_salva_todas_as_paginas_disponiveis(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_data", return_value={"page": 1, "results": [], "total_pages": 3}) as mock_fetch,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_discover_data(
                "key", mock_s3, "meu-bucket", "movie", "tmdb/discover/movie", 2023
            )

        assert mock_fetch.call_count == 4
        assert mock_save.call_count == 3

    def test_para_quando_so_ha_uma_pagina(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_data", return_value={"page": 1, "results": [], "total_pages": 1}) as mock_fetch,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_discover_data(
                "key", mock_s3, "meu-bucket", "tv", "tmdb/discover/tv", 2010
            )

        assert mock_fetch.call_count == 2
        assert mock_save.call_count == 1

    def test_s3_key_tem_formato_correto(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_data", return_value={"page": 1, "results": [], "total_pages": 1}),
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_discover_data(
                "key", mock_s3, "meu-bucket", "movie", "tmdb/discover/movie", 2023
            )

        s3_key_usado = mock_save.call_args[0][3]
        assert s3_key_usado == "tmdb/discover/movie/ano=2023/pagina_001.json"

    def test_salva_apenas_results_sem_metadados_de_paginacao(self):
        filmes = [{"id": 1, "title": "Filme A"}, {"id": 2, "title": "Filme B"}]
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_data", return_value={
                "page": 1, "results": filmes, "total_pages": 1, "total_results": 2,
            }),
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_discover_data(
                "key", mock_s3, "meu-bucket", "movie", "tmdb/discover/movie", 2023
            )

        dado_salvo = mock_save.call_args[0][2]
        ids_salvos = [item["id"] for item in dado_salvo]
        assert ids_salvos == [1, 2]
        assert "page" not in dado_salvo
        assert "total_pages" not in dado_salvo


# ---------------------------------------------------------------------------
# collect_now_playing_data
# ---------------------------------------------------------------------------


class TestCollectNowPlayingData:
    def _page_response(self, page, total_pages, results=None, dates=None):
        return {
            "page": page,
            "total_pages": total_pages,
            "results": results if results is not None else [{"id": page * 10, "title": f"Filme {page}"}],
            "dates": dates if dates is not None else {"minimum": "2025-01-01", "maximum": "2025-01-14"},
        }

    def test_pagina_unica_enriquece_com_datas_teatrais(self):
        with (
            patch("src.utils.tmdb_get") as mock_get,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            mock_get.side_effect = [
                self._page_response(1, 1, [{"id": 1, "title": "Filme X"}], {"minimum": "2025-01-01", "maximum": "2025-01-14"}),
                self._page_response(2, 1),
            ]
            mock_s3 = MagicMock()
            collect_now_playing_data("api-key", mock_s3, "meu-bucket")

        dados_salvos = mock_save.call_args[0][2]
        assert len(dados_salvos) == 1
        assert dados_salvos[0]["theater_start_date"] == "2025-01-01"
        assert dados_salvos[0]["theater_end_date"] == "2025-01-14"

    def test_multiplas_paginas_salva_cada_uma(self):
        with (
            patch("src.utils.tmdb_get") as mock_get,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            mock_get.side_effect = [
                self._page_response(1, 3),
                self._page_response(2, 3),
                self._page_response(3, 3),
                self._page_response(4, 3),
            ]
            mock_s3 = MagicMock()
            collect_now_playing_data("api-key", mock_s3, "meu-bucket")

        assert mock_save.call_count == 3

    def test_para_quando_page_maior_que_total_pages(self):
        with (
            patch("src.utils.tmdb_get") as mock_get,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            mock_get.side_effect = [
                self._page_response(1, 1),
                self._page_response(2, 1),
            ]
            mock_s3 = MagicMock()
            collect_now_playing_data("api-key", mock_s3, "meu-bucket")

        assert mock_save.call_count == 1

    def test_s3_key_tem_formato_correto(self):
        with (
            patch("src.utils.tmdb_get") as mock_get,
            patch("src.utils.save_to_s3") as mock_save,
        ):
            mock_get.side_effect = [
                self._page_response(1, 1),
                self._page_response(2, 1),
            ]
            mock_s3 = MagicMock()
            collect_now_playing_data("api-key", mock_s3, "meu-bucket")

        s3_key = mock_save.call_args[0][3]
        assert s3_key == "tmdb/now_playing/movie/pagina_001.json"


# ---------------------------------------------------------------------------
# collect_watch_providers_ref
# ---------------------------------------------------------------------------


class TestCollectWatchProvidersRef:
    def _api_response(self, results):
        return {"results": results}

    def _provider(self, pid, name, logo, priority_br):
        return {
            "provider_id": pid,
            "provider_name": name,
            "logo_path": logo,
            "display_priorities": {"BR": priority_br},
        }

    def test_movie_chama_endpoint_correto(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=self._api_response([])) as mock_fetch,
            patch("src.utils.save_to_s3"),
        ):
            collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        endpoint = mock_fetch.call_args[0][1]
        assert endpoint == "/watch/providers/movie"

    def test_tv_chama_endpoint_correto(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=self._api_response([])) as mock_fetch,
            patch("src.utils.save_to_s3"),
        ):
            collect_watch_providers_ref("key", mock_s3, "meu-bucket", "tv")

        endpoint = mock_fetch.call_args[0][1]
        assert endpoint == "/watch/providers/tv"

    def test_envia_watch_region_br(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=self._api_response([])) as mock_fetch,
            patch("src.utils.save_to_s3"),
        ):
            collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        params = mock_fetch.call_args[0][2]
        assert params == {"watch_region": "BR"}

    def test_s3_key_movie(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=self._api_response([])),
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        s3_key = mock_save.call_args[0][3]
        assert s3_key == "tmdb/watch_providers_ref/movie/watch_providers_ref.json"

    def test_s3_key_tv(self):
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=self._api_response([])),
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_watch_providers_ref("key", mock_s3, "meu-bucket", "tv")

        s3_key = mock_save.call_args[0][3]
        assert s3_key == "tmdb/watch_providers_ref/tv/watch_providers_ref.json"

    def test_extrai_campos_corretos_do_provider(self):
        provider = self._provider(8, "Netflix", "/netflix.png", 1)
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=self._api_response([provider])),
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        dados_salvos = mock_save.call_args[0][2]
        assert len(dados_salvos) == 1
        assert dados_salvos[0]["provider_id"] == 8
        assert dados_salvos[0]["provider_name"] == "Netflix"
        assert dados_salvos[0]["display_priority_br"] == 1
        assert "logo_path" not in dados_salvos[0]

    def test_display_priority_br_none_quando_ausente(self):
        provider = {"provider_id": 9, "provider_name": "Prime", "logo_path": None}
        mock_s3 = MagicMock()
        with (
            patch("src.utils.fetch_tmdb_reference", return_value=self._api_response([provider])),
            patch("src.utils.save_to_s3") as mock_save,
        ):
            collect_watch_providers_ref("key", mock_s3, "meu-bucket", "movie")

        dados_salvos = mock_save.call_args[0][2]
        assert dados_salvos[0]["display_priority_br"] is None
