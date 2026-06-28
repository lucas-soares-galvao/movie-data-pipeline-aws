import componentes


TITULO_BASE = {
    "titulo": "O Iluminado",
    "tipo": "filme",
    "ano": 1980,
    "generos": ["Terror", "Drama"],
    "sinopse": "Um escritor enlouquece num hotel isolado.",
    "nota": 8.4,
    "poster_url": "https://example.com/poster.jpg",
    "backdrop_url": None,
    "duracao": "2h 26min",
    "data_lancamento": "Maio de 1980",
    "streaming_providers": "Netflix",
    "in_theaters": False,
    "theater_end_date": None,
    "tagline": None,
    "elenco": None,
    "diretor": None,
    "keywords": None,
    "certificacao": None,
    "trailer_url": None,
    "colecao": None,
    "produtoras": None,
    "redes_tv": None,
    "criadores": None,
}


class TestRenderizarCard:
    def test_card_basico_contem_titulo(self):
        html = componentes.renderizar_card(TITULO_BASE)
        assert "O Iluminado" in html

    def test_card_com_tagline(self):
        t = {**TITULO_BASE, "tagline": "Uma frase marcante"}
        html = componentes.renderizar_card(t)
        assert "Uma frase marcante" in html
        assert "<em>" in html

    def test_card_com_elenco(self):
        t = {**TITULO_BASE, "elenco": "Jack Nicholson, Shelley Duvall"}
        html = componentes.renderizar_card(t)
        assert "Jack Nicholson" in html

    def test_card_com_diretor(self):
        t = {**TITULO_BASE, "diretor": "Stanley Kubrick"}
        html = componentes.renderizar_card(t)
        assert "Dir: Stanley Kubrick" in html

    def test_card_com_certificacao(self):
        t = {**TITULO_BASE, "certificacao": "16"}
        html = componentes.renderizar_card(t)
        assert "16" in html
        assert "certificacao-badge" in html

    def test_card_com_trailer(self):
        t = {**TITULO_BASE, "trailer_url": "https://youtube.com/watch?v=abc123"}
        html = componentes.renderizar_card(t)
        assert "https://youtube.com/watch?v=abc123" in html
        assert "Trailer" in html

    def test_card_com_colecao(self):
        t = {**TITULO_BASE, "colecao": "The Shining Collection"}
        html = componentes.renderizar_card(t)
        assert "The Shining Collection" in html

    def test_card_com_criadores(self):
        t = {**TITULO_BASE, "criadores": "Vince Gilligan"}
        html = componentes.renderizar_card(t)
        assert "Criado por: Vince Gilligan" in html

    def test_card_com_redes_tv(self):
        t = {**TITULO_BASE, "redes_tv": "HBO"}
        html = componentes.renderizar_card(t)
        assert "HBO" in html

    def test_card_sem_campos_opcionais_nao_gera_divs_vazias(self):
        html = componentes.renderizar_card(TITULO_BASE)
        assert "tagline" not in html
        assert "trailer-link" not in html
        assert "Dir:" not in html
        assert "Criado por:" not in html

    def test_card_cinema_em_cartaz(self):
        t = {**TITULO_BASE, "in_theaters": True, "theater_end_date": "15/07/2025"}
        html = componentes.renderizar_card(t)
        assert "Em cartaz até 15/07/2025" in html

    def test_card_com_streaming_providers(self):
        html = componentes.renderizar_card(TITULO_BASE)
        assert "Netflix" in html

    def test_card_escapa_xss(self):
        t = {**TITULO_BASE, "titulo": '<script>alert("xss")</script>'}
        html = componentes.renderizar_card(t)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestRenderizarGrid:
    def test_grid_vazio(self):
        html = componentes.renderizar_grid([])
        assert "grid-filmes" in html

    def test_grid_com_titulos(self):
        html = componentes.renderizar_grid([TITULO_BASE, TITULO_BASE])
        assert html.count("card") >= 2
