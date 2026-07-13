import formatacao


FAKE_TITLE = {
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


class TestFormatType:
    def test_movie_para_filme(self):
        assert formatacao._format_type("movie") == "filme"

    def test_tv_para_serie(self):
        assert formatacao._format_type("tv") == "série"

    def test_valor_desconhecido(self):
        assert formatacao._format_type("outro") == "outro"


class TestFormatGenres:
    def test_separa_por_virgula(self):
        assert formatacao._format_genres("Terror, Drama") == ["Terror", "Drama"]

    def test_retorna_lista_vazia_para_none(self):
        assert formatacao._format_genres(None) == []

    def test_retorna_lista_vazia_para_string_vazia(self):
        assert formatacao._format_genres("") == []


class TestFormatTitleDuration:
    def test_filme_com_duracao(self):
        record = {"media_type": "movie", "runtime_minutes": 146}
        assert formatacao._format_title_duration(record) == "2h 26min"

    def test_filme_sem_duracao(self):
        record = {"media_type": "movie", "runtime_minutes": None}
        assert formatacao._format_title_duration(record) is None

    def test_filme_menos_de_uma_hora(self):
        record = {"media_type": "movie", "runtime_minutes": 45}
        assert formatacao._format_title_duration(record) == "45min"

    def test_serie_completa(self):
        record = {
            "media_type": "tv",
            "number_of_seasons": 3,
            "number_of_episodes": 36,
            "episode_runtime_minutes": 45,
        }
        assert formatacao._format_title_duration(record) == "3 temporadas · 36 eps · ~45 min/ep"

    def test_serie_sem_episode_runtime(self):
        record = {
            "media_type": "tv",
            "number_of_seasons": 2,
            "number_of_episodes": 20,
            "episode_runtime_minutes": None,
        }
        assert formatacao._format_title_duration(record) == "2 temporadas · 20 eps"

    def test_serie_uma_temporada(self):
        record = {
            "media_type": "tv",
            "number_of_seasons": 1,
            "number_of_episodes": 10,
            "episode_runtime_minutes": None,
        }
        assert formatacao._format_title_duration(record) == "1 temporada · 10 eps"

    def test_serie_sem_dados(self):
        record = {
            "media_type": "tv",
            "number_of_seasons": None,
            "number_of_episodes": None,
            "episode_runtime_minutes": None,
        }
        assert formatacao._format_title_duration(record) is None


class TestFormatReleaseDate:
    def test_data_valida(self):
        assert formatacao._format_release_date("1980-05-23") == "Maio de 1980"

    def test_data_none(self):
        assert formatacao._format_release_date(None) is None

    def test_data_vazia(self):
        assert formatacao._format_release_date("") is None

    def test_data_curta(self):
        assert formatacao._format_release_date("1980") is None


class TestFormatTheaterEndDate:
    def test_em_cartaz_com_data(self):
        assert formatacao._format_theater_end_date("2025-07-15", True) == "15/07/2025"

    def test_fora_de_cartaz(self):
        assert formatacao._format_theater_end_date("2025-07-15", False) is None

    def test_em_cartaz_sem_data(self):
        assert formatacao._format_theater_end_date(None, True) is None


class TestFormatRating:
    def test_float_valido(self):
        assert formatacao._format_rating(8.4) == 8.4

    def test_string_valida(self):
        assert formatacao._format_rating("7.5") == 7.5

    def test_none(self):
        assert formatacao._format_rating(None) is None

    def test_string_vazia(self):
        assert formatacao._format_rating("") is None


class TestFormatRecord:
    def test_registro_completo_filme(self):
        result = formatacao.format_record(FAKE_TITLE)
        assert result["title"] == "O Iluminado"
        assert result["type"] == "filme"
        assert result["year"] == 1980
        assert result["genres"] == ["Terror", "Drama"]
        assert result["overview"] == "Um escritor enlouquece num hotel isolado."
        assert result["rating"] == 8.4
        assert result["poster_url"] == "https://example.com/poster.jpg"
        assert result["backdrop_url"] is None
        assert result["duration"] == "2h 26min"
        assert result["release_date"] == "Maio de 1980"
        assert result["streaming_providers"] == "Netflix"
        assert result["in_theaters"] is False
        assert result["theater_end_date"] is None

    def test_novos_campos_filme(self):
        record = {
            **FAKE_TITLE,
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
        result = formatacao.format_record(record)
        assert result["tagline"] == "Uma frase marcante"
        assert result["cast"] == "Jack Nicholson, Shelley Duvall"
        assert result["director"] == "Stanley Kubrick"
        assert result["writers"] == "Stephen King, Stanley Kubrick"
        assert result["composer"] == "Wendy Carlos"
        assert result["keywords"] == "hotel, terror psicológico"
        assert result["certification"] == "16"
        assert result["trailer_url"] == "https://youtube.com/watch?v=abc"
        assert result["collection"] is None
        assert result["production_companies"] == "Warner Bros."
        assert result["networks"] is None
        assert result["creators"] is None

    def test_novos_campos_crew_e_extras(self):
        record = {
            **FAKE_TITLE,
            "producer": "Kevin Feige",
            "cinematographer": "Roger Deakins",
            "editor": "Thelma Schoonmaker",
            "production_countries": "United States, New Zealand",
            "rent_buy_providers": "Apple TV, Google Play",
            "recommended_titles": "Interstellar, The Prestige",
            "similar_titles": "Inception, Tenet",
            "alternative_titles": "Seven, Se7en",
        }
        result = formatacao.format_record(record)
        assert result["producer"] == "Kevin Feige"
        assert result["cinematographer"] == "Roger Deakins"
        assert result["editor"] == "Thelma Schoonmaker"
        assert result["production_countries"] == "United States, New Zealand"
        assert result["rent_buy_providers"] == "Apple TV, Google Play"
        assert result["recommended"] == "Interstellar, The Prestige"
        assert result["similar"] == "Inception, Tenet"
        assert result["alternative_titles"] == "Seven, Se7en"

    def test_novos_campos_nulos(self):
        result = formatacao.format_record(FAKE_TITLE)
        assert result["tagline"] is None
        assert result["cast"] is None
        assert result["director"] is None
        assert result["writers"] is None
        assert result["composer"] is None
        assert result["producer"] is None
        assert result["cinematographer"] is None
        assert result["editor"] is None
        assert result["production_countries"] is None
        assert result["rent_buy_providers"] is None
        assert result["recommended"] is None
        assert result["similar"] is None
        assert result["alternative_titles"] is None

    def test_registro_serie(self):
        tv_show = {
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
        result = formatacao.format_record(tv_show)
        assert result["type"] == "série"
        assert result["duration"] == "4 temporadas · 34 eps · ~50 min/ep"
