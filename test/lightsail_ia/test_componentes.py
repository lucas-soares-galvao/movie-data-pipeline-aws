import componentes


BASE_TITLE = {
    "title": "O Iluminado",
    "type": "filme",
    "year": 1980,
    "genres": ["Terror", "Drama"],
    "overview": "Um escritor enlouquece num hotel isolado.",
    "rating": 8.4,
    "poster_url": "https://example.com/poster.jpg",
    "backdrop_url": None,
    "duration": "2h 26min",
    "release_date": "Maio de 1980",
    "streaming_providers": "Netflix",
    "in_theaters": False,
    "theater_end_date": None,
    "tagline": None,
    "cast": None,
    "director": None,
    "producer": None,
    "cinematographer": None,
    "editor": None,
    "keywords": None,
    "certification": None,
    "trailer_url": None,
    "collection": None,
    "production_companies": None,
    "networks": None,
    "creators": None,
}


class TestRenderCard:
    def test_card_basico_contem_titulo(self):
        html = componentes.render_card(BASE_TITLE)
        assert "O Iluminado" in html

    def test_card_ignora_tagline(self):
        t = {**BASE_TITLE, "tagline": "Uma frase marcante"}
        html = componentes.render_card(t)
        assert "Uma frase marcante" not in html

    def test_card_nao_exibe_elenco(self):
        t = {**BASE_TITLE, "cast": "Jack Nicholson, Shelley Duvall"}
        html = componentes.render_card(t)
        assert "Elenco:" not in html

    def test_card_nao_exibe_diretor(self):
        t = {**BASE_TITLE, "director": "Stanley Kubrick"}
        html = componentes.render_card(t)
        assert "Diretor:" not in html

    def test_card_com_certificacao(self):
        t = {**BASE_TITLE, "certification": "16"}
        html = componentes.render_card(t)
        assert "16" in html
        assert "certification-badge" in html

    def test_card_com_trailer(self):
        t = {**BASE_TITLE, "trailer_url": "https://youtube.com/watch?v=abc123"}
        html = componentes.render_card(t)
        assert "https://youtube.com/watch?v=abc123" in html
        assert "Trailer" in html

    def test_card_ignora_colecao(self):
        t = {**BASE_TITLE, "collection": "The Shining Collection"}
        html = componentes.render_card(t)
        assert "The Shining Collection" not in html

    def test_card_ignora_criadores(self):
        t = {**BASE_TITLE, "creators": "Vince Gilligan"}
        html = componentes.render_card(t)
        assert "Criado por:" not in html

    def test_card_ignora_redes_tv(self):
        t = {**BASE_TITLE, "networks": "HBO"}
        html = componentes.render_card(t)
        assert "networks" not in html

    def test_card_sem_campos_opcionais_nao_gera_divs_vazias(self):
        html = componentes.render_card(BASE_TITLE)
        assert "tagline" not in html
        assert "trailer-link" not in html
        assert "Diretor:" not in html
        assert "Criado por:" not in html

    def test_card_cinema_em_cartaz(self):
        t = {**BASE_TITLE, "in_theaters": True, "theater_end_date": "15/07/2025"}
        html = componentes.render_card(t)
        assert "Em cartaz até 15/07/2025" in html

    def test_card_nao_exibe_produtor(self):
        t = {**BASE_TITLE, "producer": "Kevin Feige"}
        html = componentes.render_card(t)
        assert "Produtor:" not in html

    def test_card_nao_exibe_cinematografo(self):
        t = {**BASE_TITLE, "cinematographer": "Roger Deakins"}
        html = componentes.render_card(t)
        assert "Cinematógrafo:" not in html

    def test_card_nao_exibe_montador(self):
        t = {**BASE_TITLE, "editor": "Thelma Schoonmaker"}
        html = componentes.render_card(t)
        assert "Montador:" not in html

    def test_card_com_streaming_providers(self):
        html = componentes.render_card(BASE_TITLE)
        assert "Netflix" in html

    def test_card_escapa_xss(self):
        t = {**BASE_TITLE, "title": '<script>alert("xss")</script>'}
        html = componentes.render_card(t)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderGrid:
    def test_grid_vazio(self):
        html = componentes.render_grid([])
        assert "grid-titles" in html

    def test_grid_com_titulos(self):
        html = componentes.render_grid([BASE_TITLE, BASE_TITLE])
        assert html.count("card") >= 2
