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
    "aluguel_compra": None,
    "in_theaters": False,
    "theater_end_date": None,
    "tagline": None,
    "elenco": None,
    "diretor": None,
    "produtor": None,
    "cinematografo": None,
    "montador": None,
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

    def test_card_ignora_tagline(self):
        t = {**TITULO_BASE, "tagline": "Uma frase marcante"}
        html = componentes.renderizar_card(t)
        assert "Uma frase marcante" not in html

    def test_card_com_elenco(self):
        t = {**TITULO_BASE, "elenco": "Jack Nicholson, Shelley Duvall"}
        html = componentes.renderizar_card(t)
        assert "Elenco: Jack Nicholson" in html

    def test_card_com_diretor(self):
        t = {**TITULO_BASE, "diretor": "Stanley Kubrick"}
        html = componentes.renderizar_card(t)
        assert "Diretor: Stanley Kubrick" in html

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

    def test_card_ignora_colecao(self):
        t = {**TITULO_BASE, "colecao": "The Shining Collection"}
        html = componentes.renderizar_card(t)
        assert "The Shining Collection" not in html

    def test_card_ignora_criadores(self):
        t = {**TITULO_BASE, "criadores": "Vince Gilligan"}
        html = componentes.renderizar_card(t)
        assert "Criado por:" not in html

    def test_card_ignora_redes_tv(self):
        t = {**TITULO_BASE, "redes_tv": "HBO"}
        html = componentes.renderizar_card(t)
        assert 'redes-tv' not in html

    def test_card_sem_campos_opcionais_nao_gera_divs_vazias(self):
        html = componentes.renderizar_card(TITULO_BASE)
        assert "tagline" not in html
        assert "trailer-link" not in html
        assert "Diretor:" not in html
        assert "Criado por:" not in html

    def test_card_cinema_em_cartaz(self):
        t = {**TITULO_BASE, "in_theaters": True, "theater_end_date": "15/07/2025"}
        html = componentes.renderizar_card(t)
        assert "Em cartaz até 15/07/2025" in html

    def test_card_nao_exibe_produtor(self):
        t = {**TITULO_BASE, "produtor": "Kevin Feige"}
        html = componentes.renderizar_card(t)
        assert "Produtor:" not in html

    def test_card_nao_exibe_cinematografo(self):
        t = {**TITULO_BASE, "cinematografo": "Roger Deakins"}
        html = componentes.renderizar_card(t)
        assert "Cinematógrafo:" not in html

    def test_card_nao_exibe_montador(self):
        t = {**TITULO_BASE, "montador": "Thelma Schoonmaker"}
        html = componentes.renderizar_card(t)
        assert "Montador:" not in html

    def test_card_com_rent_buy_providers(self):
        t = {**TITULO_BASE, "aluguel_compra": "Apple TV, Google Play"}
        html = componentes.renderizar_card(t)
        assert "Apple TV" in html
        assert "Google Play" in html

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
