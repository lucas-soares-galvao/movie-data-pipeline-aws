import formatacao


TITULO_FAKE = {
    "title": "O Iluminado",
    "media_type": "movie",
    "year": "1980",
    "genre_names": "Terror, Drama",
    "overview": "Um escritor enlouquece num hotel isolado.",
    "vote_average": 8.4,
    "poster_url": "https://example.com/poster.jpg",
    "backdrop_url": None,
    "runtime_minutes": 146,
    "number_of_seasons": None,
    "number_of_episodes": None,
    "episode_runtime_minutes": None,
    "streaming_providers": "Netflix",
    "air_date": "1980-05-23",
    "in_theaters": "false",
    "theater_end_date": None,
}


class TestFormatarTipo:
    def test_movie_para_filme(self):
        assert formatacao._formatar_tipo("movie") == "filme"

    def test_tv_para_serie(self):
        assert formatacao._formatar_tipo("tv") == "série"

    def test_valor_desconhecido(self):
        assert formatacao._formatar_tipo("outro") == "outro"


class TestFormatarGeneros:
    def test_separa_por_virgula(self):
        assert formatacao._formatar_generos("Terror, Drama") == ["Terror", "Drama"]

    def test_retorna_lista_vazia_para_none(self):
        assert formatacao._formatar_generos(None) == []

    def test_retorna_lista_vazia_para_string_vazia(self):
        assert formatacao._formatar_generos("") == []


class TestFormatarDuracaoTitulo:
    def test_filme_com_duracao(self):
        reg = {"media_type": "movie", "runtime_minutes": 146}
        assert formatacao._formatar_duracao_titulo(reg) == "2h 26min"

    def test_filme_sem_duracao(self):
        reg = {"media_type": "movie", "runtime_minutes": None}
        assert formatacao._formatar_duracao_titulo(reg) is None

    def test_filme_menos_de_uma_hora(self):
        reg = {"media_type": "movie", "runtime_minutes": 45}
        assert formatacao._formatar_duracao_titulo(reg) == "45min"

    def test_serie_completa(self):
        reg = {
            "media_type": "tv",
            "number_of_seasons": 3,
            "number_of_episodes": 36,
            "episode_runtime_minutes": 45,
        }
        assert formatacao._formatar_duracao_titulo(reg) == "3 temporadas · 36 eps · ~45 min/ep"

    def test_serie_sem_episode_runtime(self):
        reg = {
            "media_type": "tv",
            "number_of_seasons": 2,
            "number_of_episodes": 20,
            "episode_runtime_minutes": None,
        }
        assert formatacao._formatar_duracao_titulo(reg) == "2 temporadas · 20 eps"

    def test_serie_uma_temporada(self):
        reg = {
            "media_type": "tv",
            "number_of_seasons": 1,
            "number_of_episodes": 10,
            "episode_runtime_minutes": None,
        }
        assert formatacao._formatar_duracao_titulo(reg) == "1 temporada · 10 eps"

    def test_serie_sem_dados(self):
        reg = {
            "media_type": "tv",
            "number_of_seasons": None,
            "number_of_episodes": None,
            "episode_runtime_minutes": None,
        }
        assert formatacao._formatar_duracao_titulo(reg) is None


class TestFormatarDataLancamento:
    def test_data_valida(self):
        assert formatacao._formatar_data_lancamento("1980-05-23") == "Maio de 1980"

    def test_data_none(self):
        assert formatacao._formatar_data_lancamento(None) is None

    def test_data_vazia(self):
        assert formatacao._formatar_data_lancamento("") is None

    def test_data_curta(self):
        assert formatacao._formatar_data_lancamento("1980") is None


class TestFormatarTheaterEndDate:
    def test_em_cartaz_com_data(self):
        assert formatacao._formatar_theater_end_date("2025-07-15", True) == "15/07/2025"

    def test_fora_de_cartaz(self):
        assert formatacao._formatar_theater_end_date("2025-07-15", False) is None

    def test_em_cartaz_sem_data(self):
        assert formatacao._formatar_theater_end_date(None, True) is None


class TestFormatarNota:
    def test_float_valido(self):
        assert formatacao._formatar_nota(8.4) == 8.4

    def test_string_valida(self):
        assert formatacao._formatar_nota("7.5") == 7.5

    def test_none(self):
        assert formatacao._formatar_nota(None) is None

    def test_string_vazia(self):
        assert formatacao._formatar_nota("") is None


class TestFormatarRegistro:
    def test_registro_completo_filme(self):
        resultado = formatacao.formatar_registro(TITULO_FAKE)
        assert resultado["titulo"] == "O Iluminado"
        assert resultado["tipo"] == "filme"
        assert resultado["ano"] == 1980
        assert resultado["generos"] == ["Terror", "Drama"]
        assert resultado["sinopse"] == "Um escritor enlouquece num hotel isolado."
        assert resultado["nota"] == 8.4
        assert resultado["poster_url"] == "https://example.com/poster.jpg"
        assert resultado["backdrop_url"] is None
        assert resultado["duracao"] == "2h 26min"
        assert resultado["data_lancamento"] == "Maio de 1980"
        assert resultado["streaming_providers"] == "Netflix"
        assert resultado["in_theaters"] is False
        assert resultado["theater_end_date"] is None

    def test_novos_campos_filme(self):
        registro = {
            **TITULO_FAKE,
            "tagline": "Uma frase marcante",
            "actor_names": "Jack Nicholson, Shelley Duvall",
            "director": "Stanley Kubrick",
            "screenplay": "Stephen King, Stanley Kubrick",
            "music_composer": "Wendy Carlos",
            "keywords_pt": "hotel, terror psicológico",
            "certification": "16",
            "trailer_url": "https://youtube.com/watch?v=abc",
            "collection_name": None,
            "production_companies": "Warner Bros.",
            "networks": None,
            "created_by": None,
        }
        resultado = formatacao.formatar_registro(registro)
        assert resultado["tagline"] == "Uma frase marcante"
        assert resultado["elenco"] == "Jack Nicholson, Shelley Duvall"
        assert resultado["diretor"] == "Stanley Kubrick"
        assert resultado["roteiristas"] == "Stephen King, Stanley Kubrick"
        assert resultado["compositor"] == "Wendy Carlos"
        assert resultado["keywords"] == "hotel, terror psicológico"
        assert resultado["certificacao"] == "16"
        assert resultado["trailer_url"] == "https://youtube.com/watch?v=abc"
        assert resultado["colecao"] is None
        assert resultado["produtoras"] == "Warner Bros."
        assert resultado["redes_tv"] is None
        assert resultado["criadores"] is None

    def test_novos_campos_crew_e_extras(self):
        registro = {
            **TITULO_FAKE,
            "producer": "Kevin Feige",
            "cinematographer": "Roger Deakins",
            "editor": "Thelma Schoonmaker",
            "production_countries": "United States, New Zealand",
            "rent_buy_providers": "Apple TV, Google Play",
            "recommended_titles": "Interstellar, The Prestige",
            "similar_titles": "Inception, Tenet",
            "alternative_titles": "Seven, Se7en",
        }
        resultado = formatacao.formatar_registro(registro)
        assert resultado["produtor"] == "Kevin Feige"
        assert resultado["cinematografo"] == "Roger Deakins"
        assert resultado["montador"] == "Thelma Schoonmaker"
        assert resultado["paises_producao"] == "United States, New Zealand"
        assert resultado["aluguel_compra"] == "Apple TV, Google Play"
        assert resultado["recomendados"] == "Interstellar, The Prestige"
        assert resultado["similares"] == "Inception, Tenet"
        assert resultado["titulos_alternativos"] == "Seven, Se7en"

    def test_novos_campos_nulos(self):
        resultado = formatacao.formatar_registro(TITULO_FAKE)
        assert resultado["tagline"] is None
        assert resultado["elenco"] is None
        assert resultado["diretor"] is None
        assert resultado["roteiristas"] is None
        assert resultado["compositor"] is None
        assert resultado["produtor"] is None
        assert resultado["cinematografo"] is None
        assert resultado["montador"] is None
        assert resultado["paises_producao"] is None
        assert resultado["aluguel_compra"] is None
        assert resultado["recomendados"] is None
        assert resultado["similares"] is None
        assert resultado["titulos_alternativos"] is None

    def test_registro_serie(self):
        serie = {
            "title": "Stranger Things",
            "media_type": "tv",
            "year": "2016",
            "genre_names": "Drama, Ficção Científica",
            "overview": "Um garoto desaparece.",
            "vote_average": "8.6",
            "poster_url": None,
            "backdrop_url": None,
            "runtime_minutes": None,
            "number_of_seasons": "4",
            "number_of_episodes": "34",
            "episode_runtime_minutes": "50",
            "streaming_providers": "Netflix",
            "air_date": "2016-07-15",
            "in_theaters": "false",
            "theater_end_date": None,
        }
        resultado = formatacao.formatar_registro(serie)
        assert resultado["tipo"] == "série"
        assert resultado["duracao"] == "4 temporadas · 34 eps · ~50 min/ep"
