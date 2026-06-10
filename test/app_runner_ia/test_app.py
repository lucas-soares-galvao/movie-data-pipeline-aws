from app import _gerar_html_card, _gerar_html_grid


def _titulo_completo() -> dict:
    return {
        "titulo": "Filme Teste",
        "tipo": "filme",
        "ano": 2023,
        "generos": ["Ação", "Drama"],
        "sinopse": "Uma sinopse de teste.",
        "nota": 7.5,
        "poster_url": None,
        "backdrop_url": "https://img.example.com/backdrop.jpg",
        "duracao": "1h 52min",
        "streaming_providers": "Netflix, Amazon Prime Video",
        "motivo": "Excelente filme de ação",
    }


# ── TestGerarHtmlCard ──────────────────────────────────────────────────────────

class TestGerarHtmlCard:
    def test_inclui_titulo(self):
        html = _gerar_html_card(_titulo_completo())
        assert "Filme Teste" in html

    def test_inclui_nota(self):
        html = _gerar_html_card(_titulo_completo())
        assert "7.5" in html

    def test_inclui_duracao(self):
        html = _gerar_html_card(_titulo_completo())
        assert "1h 52min" in html

    def test_inclui_badges_de_generos(self):
        html = _gerar_html_card(_titulo_completo())
        assert "Ação" in html
        assert "Drama" in html

    def test_inclui_badges_de_streaming(self):
        html = _gerar_html_card(_titulo_completo())
        assert "Netflix" in html
        assert "Amazon Prime Video" in html

    def test_inclui_imagem_quando_backdrop_disponivel(self):
        html = _gerar_html_card(_titulo_completo())
        assert "<img" in html
        assert "https://img.example.com/backdrop.jpg" in html

    def test_sem_imagem_quando_urls_ausentes(self):
        titulo = {**_titulo_completo(), "backdrop_url": None, "poster_url": None}
        html = _gerar_html_card(titulo)
        assert "<img" not in html

    def test_prefere_backdrop_ao_poster(self):
        titulo = {
            **_titulo_completo(),
            "backdrop_url": "https://backdrop.jpg",
            "poster_url": "https://poster.jpg",
        }
        html = _gerar_html_card(titulo)
        assert "https://backdrop.jpg" in html
        assert "https://poster.jpg" not in html

    def test_sem_nota_quando_ausente(self):
        titulo = {**_titulo_completo(), "nota": None}
        html = _gerar_html_card(titulo)
        assert 'class="nota"' not in html

    def test_sem_providers_quando_ausente(self):
        titulo = {**_titulo_completo(), "streaming_providers": None}
        html = _gerar_html_card(titulo)
        assert 'class="provider"' not in html

    def test_limpa_duracao_com_null(self):
        titulo = {**_titulo_completo(), "duracao": "3 temporadas · ~null"}
        html = _gerar_html_card(titulo)
        assert "~null" not in html
        assert "null" not in html


# ── TestGerarHtmlGrid ──────────────────────────────────────────────────────────

class TestGerarHtmlGrid:
    def test_envolve_cards_em_div_grid(self):
        html = _gerar_html_grid([_titulo_completo()])
        assert 'class="grid-filmes"' in html

    def test_inclui_todos_os_titulos(self):
        titulos = [
            {**_titulo_completo(), "titulo": "Filme A"},
            {**_titulo_completo(), "titulo": "Filme B"},
        ]
        html = _gerar_html_grid(titulos)
        assert "Filme A" in html
        assert "Filme B" in html

    def test_colapsa_espacos_extras(self):
        html = _gerar_html_grid([_titulo_completo()])
        assert "\n" not in html
        assert "  " not in html
