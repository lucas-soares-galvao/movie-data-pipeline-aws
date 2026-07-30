import componentes

BASE_TITLE = {
    "title": "O Iluminado",
    "type": "filme",
    "year": 1980,
    "genres": ["Terror", "Drama"],
    "overview": "Um escritor enlouquece num hotel isolado.",
    "reason": None,
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


class TestPrioritize:
    """_prioritize() reordena badges colocando primeiro os que casam com algum termo
    destacado (case-insensitive), preservando a ordem relativa dentro de cada grupo."""

    def test_sem_termos_retorna_lista_original(self):
        assert componentes._prioritize(["Terror", "Drama"], []) == ["Terror", "Drama"]

    def test_item_casado_vai_para_o_inicio(self):
        result = componentes._prioritize(["Drama", "Terror", "Comédia"], ["terror"])
        assert result == ["Terror", "Drama", "Comédia"]

    def test_mantem_ordem_relativa_dentro_de_cada_grupo(self):
        result = componentes._prioritize(
            ["Drama", "Ação", "Terror", "Comédia"], ["terror", "comédia"]
        )
        assert result == ["Terror", "Comédia", "Drama", "Ação"]

    def test_case_insensitive(self):
        result = componentes._prioritize(["Drama", "Terror"], ["TERROR"])
        assert result == ["Terror", "Drama"]

    def test_termo_curto_bate_em_mais_de_um_genero(self):
        result = componentes._prioritize(["Drama", "Ação & Aventura", "Animação"], ["ação"])
        assert result == ["Ação & Aventura", "Animação", "Drama"]

    def test_termo_curto_bate_em_mais_de_um_provedor(self):
        result = componentes._prioritize(["Netflix", "Google Play", "Globoplay"], ["play"])
        assert result == ["Google Play", "Globoplay", "Netflix"]

    def test_lista_vazia_com_termos_nao_gera_erro(self):
        assert componentes._prioritize([], ["terror"]) == []


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
        assert 'class="vital vital-trailer"' in html

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

    def test_card_sem_streaming_providers_nao_exibe_rotulo(self):
        t = {**BASE_TITLE, "streaming_providers": None}
        html = componentes.render_card(t)
        assert "Onde assistir" not in html
        assert "providers-label" not in html

    def test_card_generos_dentro_do_limite_nao_exibe_badge_extra(self):
        t = {
            **BASE_TITLE,
            "genres": ["Terror", "Drama", "Suspense", "Ficção", "Ação", "Aventura"],
        }
        html = componentes.render_card(t)
        assert "genre-more" not in html

    def test_card_generos_acima_do_limite_trunca_sem_indicador(self):
        t = {
            **BASE_TITLE,
            "genres": [
                "Terror", "Drama", "Suspense", "Ficção", "Ação", "Aventura", "Mistério", "Comédia",
            ],
        }
        html = componentes.render_card(t)
        assert "genre-more" not in html
        assert "+2" not in html
        assert "Mistério" not in html
        assert "Comédia" not in html

    def test_card_providers_dentro_do_limite_nao_exibe_badge_extra(self):
        t = {
            **BASE_TITLE,
            "streaming_providers": (
                "Netflix,HBO Max,Disney Plus,Crunchyroll,Amazon Prime Video,Telecine"
            ),
        }
        html = componentes.render_card(t)
        assert "provider-more" not in html

    def test_card_providers_acima_do_limite_trunca_sem_indicador(self):
        t = {
            **BASE_TITLE,
            "streaming_providers": (
                "Netflix,HBO Max,Disney Plus,Crunchyroll,Amazon Prime Video,Telecine,Globoplay"
            ),
        }
        html = componentes.render_card(t)
        assert "provider-more" not in html
        assert "+1" not in html
        assert "Globoplay" not in html

    def test_card_genero_destacado_entra_nos_visiveis_alem_do_limite(self):
        t = {
            **BASE_TITLE,
            "genres": [
                "Drama", "Suspense", "Ficção", "Ação", "Aventura", "Comédia", "Terror",
            ],
            "highlighted_genres": ["terror"],
        }
        html = componentes.render_card(t)
        assert '<span class="genre">Terror</span>' in html
        assert "Comédia" not in html

    def test_card_provedor_destacado_entra_nos_visiveis_alem_do_limite(self):
        t = {
            **BASE_TITLE,
            "streaming_providers": (
                "Netflix,HBO Max,Disney Plus,Amazon Prime Video,Telecine,Globoplay,Crunchyroll"
            ),
            "highlighted_providers": ["crunchyroll"],
        }
        html = componentes.render_card(t)
        assert '<span class="provider">Crunchyroll</span>' in html
        assert "Globoplay" not in html

    def test_card_multiplos_generos_destacados_mantem_ordem_entre_si(self):
        t = {
            **BASE_TITLE,
            "genres": ["Drama", "Terror", "Comédia"],
            "highlighted_genres": ["terror", "comédia"],
        }
        html = componentes.render_card(t)
        terror_pos = html.index(">Terror<")
        comedia_pos = html.index(">Comédia<")
        drama_pos = html.index(">Drama<")
        assert terror_pos < comedia_pos < drama_pos

    def test_card_generos_e_provedores_destacados_priorizam_fileiras_independentes(self):
        t = {
            **BASE_TITLE,
            "genres": ["Drama", "Terror"],
            "streaming_providers": "Netflix,Crunchyroll",
            "highlighted_genres": ["terror"],
            "highlighted_providers": ["crunchyroll"],
        }
        html = componentes.render_card(t)
        assert html.index(">Terror<") < html.index(">Drama<")
        assert html.index(">Crunchyroll<") < html.index(">Netflix<")

    def test_card_sem_chave_highlighted_ordem_permanece_igual(self):
        t = {**BASE_TITLE, "genres": ["Drama", "Terror"]}
        html = componentes.render_card(t)
        assert html.index(">Drama<") < html.index(">Terror<")

    def test_card_highlighted_vazio_ordem_permanece_igual(self):
        t = {
            **BASE_TITLE,
            "genres": ["Drama", "Terror"],
            "highlighted_genres": [],
            "highlighted_providers": [],
        }
        html = componentes.render_card(t)
        assert html.index(">Drama<") < html.index(">Terror<")

    def test_card_vitals_combina_nota_data_e_trailer(self):
        t = {**BASE_TITLE, "trailer_url": "https://youtube.com/watch?v=abc123"}
        html = componentes.render_card(t)
        assert 'class="meta-row vitals-row"' in html
        assert "★ 8.4" in html
        assert "📅 Maio de 1980" in html
        assert "Trailer" in html
        assert html.count('class="vital-sep">·</span>') == 2
        rating_pos = html.index("★ 8.4")
        date_pos = html.index("📅 Maio de 1980")
        trailer_pos = html.index("vital-trailer")
        assert rating_pos < date_pos < trailer_pos

    def test_card_duracao_fica_em_linha_separada_apos_vitals(self):
        html = componentes.render_card(BASE_TITLE)
        rating_pos = html.index("★ 8.4")
        date_pos = html.index("📅 Maio de 1980")
        duration_pos = html.index("⏱ 2h 26min")
        assert rating_pos < date_pos < duration_pos

    def test_card_vitals_omite_nota_ausente_sem_separador_solto(self):
        t = {**BASE_TITLE, "rating": None}
        html = componentes.render_card(t)
        assert "★" not in html
        assert "vitals-row" in html
        assert html.count('class="vital-sep">·</span>') == 0

    def test_card_sem_vitals_nao_gera_linha_vazia(self):
        t = {**BASE_TITLE, "rating": None, "duration": None, "release_date": None}
        html = componentes.render_card(t)
        assert "vitals-row" not in html

    def test_card_exibe_motivo(self):
        t = {**BASE_TITLE, "reason": "Nota alta e mesmo gênero pedido."}
        html = componentes.render_card(t)
        assert "Nota alta e mesmo gênero pedido." in html
        assert 'class="reason"' in html

    def test_card_escapa_xss(self):
        t = {**BASE_TITLE, "title": '<script>alert("xss")</script>'}
        html = componentes.render_card(t)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_card_escapa_xss_no_motivo(self):
        t = {**BASE_TITLE, "reason": '<script>alert("xss")</script>'}
        html = componentes.render_card(t)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_card_sinopse_curta_nao_exibe_ver_mais(self):
        html = componentes.render_card(BASE_TITLE)
        assert "Ver mais" not in html
        assert "Ver menos" not in html
        assert 'class="overview"' in html

    def test_card_sinopse_longa_trunca_com_ver_mais_e_ver_menos(self):
        sinopse_longa = "Um escritor enlouquece num hotel isolado. " * 10
        t = {**BASE_TITLE, "overview": sinopse_longa}
        html = componentes.render_card(t)
        assert "Ver mais" in html
        assert "Ver menos" in html
        assert 'class="overview overview-short"' in html
        assert 'class="overview overview-full"' in html
        assert sinopse_longa in html
        assert "…" in html

    def test_card_ver_mais_e_ver_menos_apontam_pro_mesmo_checkbox(self):
        sinopse_longa = "Um escritor enlouquece num hotel isolado. " * 10
        t = {**BASE_TITLE, "overview": sinopse_longa}
        html = componentes.render_card(t, idx=5)
        assert 'for="overview-toggle-5" class="overview-more-label"' in html
        assert 'for="overview-toggle-5" class="overview-less-label"' in html

    def test_card_toggle_id_usa_indice(self):
        sinopse_longa = "Um escritor enlouquece num hotel isolado. " * 10
        t = {**BASE_TITLE, "overview": sinopse_longa}
        html = componentes.render_card(t, idx=3)
        assert "overview-toggle-3" in html


class TestRenderGrid:
    def test_grid_vazio(self):
        html = componentes.render_grid([])
        assert "grid-titles" in html

    def test_grid_com_titulos(self):
        html = componentes.render_grid([BASE_TITLE, BASE_TITLE])
        assert html.count("card") >= 2

    def test_grid_gera_ids_de_toggle_unicos_por_indice(self):
        sinopse_longa = "Um escritor enlouquece num hotel isolado. " * 10
        t = {**BASE_TITLE, "overview": sinopse_longa}
        html = componentes.render_grid([t, t])
        assert "overview-toggle-0" in html
        assert "overview-toggle-1" in html
