from datetime import date, timedelta

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
        assert formatacao._format_type("movie") == "Filme"

    def test_tv_para_serie(self):
        assert formatacao._format_type("tv") == "Série"

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
        assert formatacao._format_title_duration(record) == "3 temps · 36 eps · ~45 min/ep"

    def test_serie_sem_episode_runtime(self):
        record = {
            "media_type": "tv",
            "number_of_seasons": 2,
            "number_of_episodes": 20,
            "episode_runtime_minutes": None,
        }
        assert formatacao._format_title_duration(record) == "2 temps · 20 eps"

    def test_serie_uma_temporada(self):
        record = {
            "media_type": "tv",
            "number_of_seasons": 1,
            "number_of_episodes": 10,
            "episode_runtime_minutes": None,
        }
        assert formatacao._format_title_duration(record) == "1 temp · 10 eps"

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
        assert formatacao._format_release_date("1980-05-23") == "Mai de 1980"

    def test_data_none(self):
        assert formatacao._format_release_date(None) is None

    def test_data_vazia(self):
        assert formatacao._format_release_date("") is None

    def test_data_curta(self):
        assert formatacao._format_release_date("1980") is None


class TestFormatAdaptiveDate:
    """Cobre a formatação compartilhada por theater_end_date, next_episode_date e
    upcoming_date (ver format_record()) — DD/MM perto de hoje, Mês de Ano quando distante."""

    _HOJE = date(2026, 1, 1)

    def test_dentro_do_threshold_no_futuro_retorna_dd_mm(self):
        alvo = self._HOJE + timedelta(days=30)
        assert formatacao._format_adaptive_date(alvo.isoformat(), today=self._HOJE) == alvo.strftime("%d/%m")

    def test_no_limite_exato_do_threshold_retorna_dd_mm(self):
        alvo = self._HOJE + timedelta(days=formatacao._ADAPTIVE_DATE_THRESHOLD_DAYS)
        assert formatacao._format_adaptive_date(alvo.isoformat(), today=self._HOJE) == alvo.strftime("%d/%m")

    def test_um_dia_alem_do_threshold_retorna_mes_de_ano(self):
        alvo = self._HOJE + timedelta(days=formatacao._ADAPTIVE_DATE_THRESHOLD_DAYS + 1)
        esperado = f"{formatacao._MONTHS[alvo.month]} de {alvo.year}"
        assert formatacao._format_adaptive_date(alvo.isoformat(), today=self._HOJE) == esperado

    def test_bem_distante_no_futuro_retorna_mes_de_ano(self):
        assert formatacao._format_adaptive_date("2027-06-15", today=self._HOJE) == "Jun de 2027"

    def test_dentro_do_threshold_no_passado_retorna_dd_mm(self):
        # theater_end_date/next_episode_date na prática nunca vêm no passado, mas a função é
        # simétrica (abs()) por robustez.
        alvo = self._HOJE - timedelta(days=30)
        assert formatacao._format_adaptive_date(alvo.isoformat(), today=self._HOJE) == alvo.strftime("%d/%m")

    def test_bem_distante_no_passado_retorna_mes_de_ano(self):
        assert formatacao._format_adaptive_date("2020-01-01", today=self._HOJE) == "Jan de 2020"

    def test_data_none(self):
        assert formatacao._format_adaptive_date(None, today=self._HOJE) is None

    def test_data_vazia(self):
        assert formatacao._format_adaptive_date("", today=self._HOJE) is None

    def test_data_malformada(self):
        assert formatacao._format_adaptive_date("2026-09", today=self._HOJE) is None

    def test_sem_today_usa_data_real_do_sistema(self):
        # Sem injetar `today`, cai na data real (UTC) — uma data bem distante no futuro
        # (ano 9999) sempre bate como "Mês de Ano" independente de quando o teste rodar.
        assert formatacao._format_adaptive_date("9999-12-31") == "Dez de 9999"


class TestIsUpcoming:
    _HOJE = date(2026, 1, 1)

    def test_data_futura_retorna_true(self):
        assert formatacao._is_upcoming("2026-09-15", today=self._HOJE) is True

    def test_data_passada_retorna_false(self):
        assert formatacao._is_upcoming("2020-01-01", today=self._HOJE) is False

    def test_data_igual_a_hoje_retorna_false(self):
        # Lançado exatamente hoje já conta como lançado, não "em breve".
        assert formatacao._is_upcoming("2026-01-01", today=self._HOJE) is False

    def test_data_none(self):
        assert formatacao._is_upcoming(None, today=self._HOJE) is False

    def test_data_vazia(self):
        assert formatacao._is_upcoming("", today=self._HOJE) is False

    def test_data_malformada(self):
        assert formatacao._is_upcoming("2026-09", today=self._HOJE) is False

    def test_sem_today_usa_data_real_do_sistema(self):
        # Sem injetar `today`, cai na data real (UTC) — uma data bem distante no futuro
        # (ano 9999) sempre bate como "em breve" independente de quando o teste rodar.
        assert formatacao._is_upcoming("9999-12-31") is True


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
        assert result["type"] == "Filme"
        assert result["year"] == 1980
        assert result["genres"] == ["Terror", "Drama"]
        assert result["overview"] == "Um escritor enlouquece num hotel isolado."
        assert result["rating"] == 8.4
        assert result["poster_url"] == "https://example.com/poster.jpg"
        assert result["backdrop_url"] is None
        assert result["duration"] == "2h 26min"
        assert result["release_date"] == "Mai de 1980"
        assert result["upcoming_date"] is None  # air_date de 1980, já lançado
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

    def test_registro_serie_com_proximo_episodio(self):
        # `today` injetado (ver TestFormatAdaptiveDate) pra manter a data dentro do threshold
        # de forma determinística, independente de quando o teste rodar.
        record = {
            **FAKE_TITLE,
            "media_type": "tv",
            "next_episode_season_number": "3",
            "next_episode_number": "1",
            "next_episode_air_date": "2026-09-15",
        }
        result = formatacao.format_record(record, today=date(2026, 9, 1))
        assert result["next_episode_season_number"] == 3
        assert result["next_episode_number"] == 1
        assert result["next_episode_date"] == "15/09"

    def test_registro_serie_com_proximo_episodio_distante(self):
        # Fora do threshold de _format_adaptive_date: vira "Mês de Ano", sem dia.
        record = {
            **FAKE_TITLE,
            "media_type": "tv",
            "next_episode_season_number": "3",
            "next_episode_number": "1",
            "next_episode_air_date": "2026-09-15",
        }
        result = formatacao.format_record(record, today=date(2026, 1, 1))
        assert result["next_episode_date"] == "Set de 2026"

    def test_registro_filme_em_cartaz(self):
        # `theater_end_date` também passa por _format_adaptive_date — dentro do threshold
        # (data injetada), vira "DD/MM".
        record = {
            **FAKE_TITLE,
            "in_theaters": "true",
            "theater_end_date": "2026-02-01",
        }
        result = formatacao.format_record(record, today=date(2026, 1, 1))
        assert result["in_theaters"] is True
        assert result["theater_end_date"] == "01/02"

    def test_registro_serie_sem_proximo_episodio(self):
        record = {
            **FAKE_TITLE,
            "media_type": "tv",
            "next_episode_season_number": None,
            "next_episode_number": None,
            "next_episode_air_date": None,
        }
        result = formatacao.format_record(record)
        assert result["next_episode_season_number"] is None
        assert result["next_episode_number"] is None
        assert result["next_episode_date"] is None

    def test_registro_com_lancamento_futuro(self):
        # Data bem distante no futuro (ano 9999) evita flakiness — sempre "em breve"
        # independente de quando o teste rodar (mesma técnica de
        # TestIsUpcoming.test_sem_today_usa_data_real_do_sistema). Mesmo texto de
        # release_date (formato "Mês de Ano", sem dia — ver _is_upcoming()).
        record = {**FAKE_TITLE, "air_date": "9999-12-31"}
        result = formatacao.format_record(record)
        assert result["upcoming_date"] == "Dez de 9999"

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
        assert result["type"] == "Série"
        assert result["duration"] == "4 temps · 34 eps · ~50 min/ep"
