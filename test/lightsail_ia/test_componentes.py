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
    "next_episode_season_number": None,
    "next_episode_number": None,
    "next_episode_date": None,
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

# BASE_TITLE tem poster_url, então usa o layout novo (nota/classificação sobre a imagem,
# trailer na meta-line). Este fixture cobre o fallback sem pôster (layout anterior: nota/
# classificação na meta-row, trailer e provedores na mesma linha).
TITLE_SEM_POSTER = {**BASE_TITLE, "poster_url": None, "backdrop_url": None}


class TestLoadAudioTimerScript:
    def test_injeta_script_via_components_html(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_audio_timer_script(15)
        assert "audio-timer-badge" in captured["content"]
        assert captured["height"] == 0

    def test_substitui_max_seconds_no_template(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_audio_timer_script(15)
        assert "__MAX_SECONDS__" not in captured["content"]
        assert "const maxSeconds = 15;" in captured["content"]


class TestRenderFeedback:
    def test_renderiza_classe_error(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.st, "markdown",
            lambda content, unsafe_allow_html=False: captured.update(content=content),
        )
        componentes.render_feedback("error", "Algo deu errado.")
        assert 'class="msg-error"' in captured["content"]
        assert "❌" in captured["content"]

    def test_renderiza_classe_warning(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.st, "markdown",
            lambda content, unsafe_allow_html=False: captured.update(content=content),
        )
        componentes.render_feedback("warning", "Fique atento.")
        assert 'class="msg-warning"' in captured["content"]
        assert "⚠️" in captured["content"]

    def test_escapa_xss_na_mensagem(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.st, "markdown",
            lambda content, unsafe_allow_html=False: captured.update(content=content),
        )
        componentes.render_feedback("error", '<script>alert("xss")</script>')
        assert "<script>" not in captured["content"]
        assert "&lt;script&gt;" in captured["content"]

    def test_extra_html_nao_e_escapado(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.st, "markdown",
            lambda content, unsafe_allow_html=False: captured.update(content=content),
        )
        componentes.render_feedback(
            "warning", "Disponível em", extra_html='<span id="countdown"></span>'
        )
        assert '<span id="countdown"></span>' in captured["content"]

    def test_sem_extra_html_nao_inclui_span(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.st, "markdown",
            lambda content, unsafe_allow_html=False: captured.update(content=content),
        )
        componentes.render_feedback("error", "Mensagem simples.")
        assert "<span" not in captured["content"]


class TestLoadCountdownScript:
    def test_injeta_script_via_components_html(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_countdown_script(42)
        assert "countdown" in captured["content"]
        assert captured["height"] == 0

    def test_substitui_seconds_no_template(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_countdown_script(42)
        assert "__SECONDS__" not in captured["content"]
        assert "let remaining = 42;" in captured["content"]

    def test_usa_countdown_como_element_id_padrao(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_countdown_script(42)
        assert 'getElementById("countdown")' in captured["content"]

    def test_substitui_element_id_customizado(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_countdown_script(42, element_id="audio-countdown")
        assert "__ELEMENT_ID__" not in captured["content"]
        assert 'getElementById("audio-countdown")' in captured["content"]


class TestLoadLoginButtonToggleScript:
    def test_injeta_script_via_components_html(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_login_button_toggle_script(False)
        assert "btn_entrar" in captured["content"]
        assert captured["height"] == 0

    def test_substitui_locked_out_false(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_login_button_toggle_script(False)
        assert "__LOCKED_OUT__" not in captured["content"]
        assert "const lockedOut = false;" in captured["content"]

    def test_substitui_locked_out_true(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            componentes.components, "html",
            lambda content, height=0: captured.update(content=content, height=height),
        )
        componentes.load_login_button_toggle_script(True)
        assert "const lockedOut = true;" in captured["content"]


class TestMatchesHighlighted:
    """_matches_highlighted() diz se um item contém (case-insensitive) algum termo
    destacado pela busca do usuário — usada tanto por _prioritize() (ordena) quanto pelo
    render de badges (decide a classe "highlighted")."""

    def test_sem_termos_retorna_falso(self):
        assert componentes._matches_highlighted("Terror", []) is False

    def test_item_bate_com_termo(self):
        assert componentes._matches_highlighted("Terror", ["terror"]) is True

    def test_item_nao_bate_com_termo(self):
        assert componentes._matches_highlighted("Drama", ["terror"]) is False

    def test_case_insensitive(self):
        assert componentes._matches_highlighted("Terror", ["TERROR"]) is True


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


class TestParseProviderNames:
    """_parse_provider_names() faz o parsing de um grupo de provedores (streaming ou
    aluguel/compra) a partir da string comma-joined vinda de glue_agg."""

    def test_separa_nomes_por_virgula(self):
        nomes = componentes._parse_provider_names("Netflix,HBO Max")
        assert nomes == ["Netflix", "HBO Max"]

    def test_remove_espacos_em_volta_de_cada_nome(self):
        nomes = componentes._parse_provider_names("Netflix, HBO Max , Disney Plus")
        assert nomes == ["Netflix", "HBO Max", "Disney Plus"]

    def test_names_vazio_retorna_lista_vazia(self):
        assert componentes._parse_provider_names("") == []

    def test_none_retorna_lista_vazia(self):
        assert componentes._parse_provider_names(None) == []


class TestRenderProviderBadges:
    """_render_provider_badges() monta os badges de texto de provedor."""

    def test_renderiza_nome_como_texto_visivel(self):
        html = componentes._render_provider_badges(["Netflix"], [])
        assert '<span class="provider-badge">Netflix</span>' in html

    def test_nao_renderiza_imagem(self):
        html = componentes._render_provider_badges(["Netflix"], [])
        assert "<img" not in html

    def test_escapa_html_no_nome(self):
        html = componentes._render_provider_badges(["<b>X</b>"], [])
        assert "<script>" not in html
        assert "&lt;b&gt;X&lt;/b&gt;" in html

    def test_prioriza_provedor_destacado(self):
        html = componentes._render_provider_badges(["Netflix", "Crunchyroll"], ["crunchyroll"])
        assert html.index("Crunchyroll") < html.index("Netflix")

    def test_provedor_destacado_ganha_classe_highlighted(self):
        html = componentes._render_provider_badges(["Netflix", "Crunchyroll"], ["crunchyroll"])
        assert '<span class="provider-badge highlighted">Crunchyroll</span>' in html
        assert '<span class="provider-badge">Netflix</span>' in html

    def test_corta_no_limite_de_provedores_visiveis(self):
        # Sem toggle "+N": acima do teto, trunca silenciosamente — saber exatamente quantos
        # badges couberam antes de quebrar linha exigiria JS medindo o DOM real, o que esse
        # componente não tem (risco aceito conscientemente, ver lightsail_ia.md).
        nomes = [f"Provedor{i}" for i in range(componentes._MAX_VISIBLE_PROVIDER_BADGES + 2)]
        html = componentes._render_provider_badges(nomes, [])
        assert "Provedor0" in html
        assert f"Provedor{componentes._MAX_VISIBLE_PROVIDER_BADGES}" not in html
        assert "provider-badge-more" not in html
        assert "providers-toggle" not in html


class TestRenderCard:
    def test_card_basico_contem_titulo(self):
        html = componentes.render_card(BASE_TITLE)
        assert "O Iluminado" in html

    def test_card_ignora_tagline(self):
        t = {**BASE_TITLE, "tagline": "Uma frase marcante"}
        html = componentes.render_card(t)
        assert "Uma frase marcante" not in html

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

    def test_card_exibe_criadores_na_ficha_tecnica(self):
        t = {**BASE_TITLE, "creators": "Vince Gilligan"}
        html = componentes.render_card(t)
        assert "<strong>Criador(es):</strong> Vince Gilligan" in html

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

    def test_card_proximo_episodio_serie(self):
        t = {
            **BASE_TITLE,
            "type": "Série",
            "next_episode_season_number": 3,
            "next_episode_number": 1,
            "next_episode_date": "15/09",
        }
        html = componentes.render_card(t)
        assert "T3E1 estreia em 15/09" in html

    def test_card_em_cartaz_tem_prioridade_sobre_proximo_episodio(self):
        t = {
            **BASE_TITLE,
            "in_theaters": True,
            "theater_end_date": "15/07/2025",
            "next_episode_season_number": 3,
            "next_episode_number": 1,
            "next_episode_date": "15/09",
        }
        html = componentes.render_card(t)
        assert "Em cartaz até 15/07/2025" in html
        assert "estreia em" not in html

    def test_card_sem_proximo_episodio_nao_exibe_badge(self):
        t = {**BASE_TITLE, "type": "Série"}
        html = componentes.render_card(t)
        assert "estreia em" not in html

    def test_card_sem_em_cartaz_nem_proximo_episodio_nao_gera_cinema_row(self):
        # Sem conteúdo pra nenhum dos dois badges, a div nem é gerada (meio solto, ver
        # principal.css) — diferente de meta-line, que é sempre emitida mesmo vazia.
        html = componentes.render_card(BASE_TITLE)
        assert "cinema-row" not in html

    def test_card_exibe_produtor_na_ficha_tecnica(self):
        t = {**BASE_TITLE, "producer": "Kevin Feige"}
        html = componentes.render_card(t)
        assert "<strong>Produção:</strong> Kevin Feige" in html

    def test_card_exibe_fotografia_na_ficha_tecnica(self):
        t = {**BASE_TITLE, "cinematographer": "Roger Deakins"}
        html = componentes.render_card(t)
        assert "<strong>Fotografia:</strong> Roger Deakins" in html

    def test_card_exibe_montagem_na_ficha_tecnica(self):
        t = {**BASE_TITLE, "editor": "Thelma Schoonmaker"}
        html = componentes.render_card(t)
        assert "<strong>Montagem:</strong> Thelma Schoonmaker" in html

    def test_card_com_streaming_providers(self):
        html = componentes.render_card(BASE_TITLE)
        assert "Netflix" in html

    def test_card_provedor_tem_icone(self):
        html = componentes.render_card(BASE_TITLE)
        assert "📺" in html

    def test_card_sem_streaming_providers_nao_exibe_rotulo(self):
        t = {**BASE_TITLE, "streaming_providers": None}
        html = componentes.render_card(t)
        assert "Onde assistir" not in html
        assert "providers-label" not in html

    def test_card_sem_provedor_nao_gera_icone(self):
        t = {**BASE_TITLE, "streaming_providers": None}
        html = componentes.render_card(t)
        assert "📺" not in html

    def test_card_ignora_campo_de_logo_do_provedor(self):
        """streaming_provider_logos/rent_buy_provider_logos não são mais buscados nem
        formatados — se aparecerem no dict do card por algum outro motivo, o card
        continua ignorando-os e renderiza o nome do provedor só como texto."""
        t = {
            **BASE_TITLE,
            "streaming_providers": "Netflix",
            "streaming_provider_logos": "https://image.tmdb.org/t/p/w45/netflix.png",
        }
        html = componentes.render_card(t)
        assert '<span class="provider-badge">Netflix</span>' in html
        assert "netflix.png" not in html

    def test_card_sem_rent_buy_providers_nao_exibe_bloco(self):
        html = componentes.render_card(BASE_TITLE)
        assert "Aluguel/Compra" not in html

    def test_card_com_rent_buy_providers_exibe_bloco(self):
        t = {**BASE_TITLE, "rent_buy_providers": "Apple TV,Google Play"}
        html = componentes.render_card(t)
        assert "Aluguel/Compra" not in html  # rótulo foi removido, provedores viram só badges
        assert '<span class="provider-badge">Apple TV</span>' in html
        assert '<span class="provider-badge">Google Play</span>' in html

    def test_card_streaming_e_rent_buy_combinados_e_deduplicados(self):
        t = {
            **BASE_TITLE,
            "streaming_providers": "Netflix,Apple TV",
            "rent_buy_providers": "Apple TV,Google Play",
        }
        html = componentes.render_card(t)
        assert html.count('<span class="provider-badge">Apple TV</span>') == 1

    def test_card_generos_dentro_do_limite_nao_exibe_badge_extra(self):
        t = {**BASE_TITLE, "genres": ["Terror", "Drama", "Suspense"]}
        html = componentes.render_card(t)
        assert "genre-more" not in html
        assert '<span class="genre">Terror</span>' in html
        assert '<span class="genre">Drama</span>' in html
        assert '<span class="genre">Suspense</span>' in html

    def test_card_generos_tem_icone(self):
        html = componentes.render_card(BASE_TITLE)
        assert "🎭" in html

    def test_card_sem_generos_nao_gera_icone(self):
        t = {**BASE_TITLE, "genres": []}
        html = componentes.render_card(t)
        assert "🎭" not in html

    def test_card_generos_acima_do_limite_trunca_sem_indicador(self):
        t = {
            **BASE_TITLE,
            "genres": [
                "Terror", "Drama", "Suspense", "Ficção", "Ação", "Aventura",
                "Comédia", "Romance",
            ],
        }
        html = componentes.render_card(t)
        assert "genre-more" not in html
        assert "+2" not in html
        assert "Comédia" not in html
        assert "Romance" not in html

    def test_card_providers_acima_do_teto_maximo_trunca_sem_indicador(self):
        t = {
            **BASE_TITLE,
            "streaming_providers": (
                "Netflix,HBO Max,Disney Plus,Crunchyroll,Amazon Prime Video,Telecine,Globoplay"
            ),
        }
        html = componentes.render_card(t)
        assert "Globoplay" not in html  # 7º provedor, acima do teto máximo de 6

    def test_card_genero_destacado_entra_nos_visiveis_alem_do_limite(self):
        t = {
            **BASE_TITLE,
            "genres": [
                "Drama", "Suspense", "Ficção", "Ação", "Aventura", "Comédia", "Terror",
            ],
            "highlighted_genres": ["terror"],
        }
        html = componentes.render_card(t)
        assert '<span class="genre highlighted">Terror</span>' in html
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
        assert '<span class="provider-badge highlighted">Crunchyroll</span>' in html
        assert "Globoplay" not in html

    def test_card_genero_destacado_ganha_classe_highlighted_e_nao_destacado_nao_ganha(self):
        t = {
            **BASE_TITLE,
            "genres": ["Drama", "Terror"],
            "highlighted_genres": ["terror"],
        }
        html = componentes.render_card(t)
        assert '<span class="genre highlighted">Terror</span>' in html
        assert '<span class="genre">Drama</span>' in html

    def test_card_provedor_destacado_ganha_classe_highlighted_e_nao_destacado_nao_ganha(self):
        t = {
            **BASE_TITLE,
            "streaming_providers": "Netflix,Crunchyroll",
            "highlighted_providers": ["crunchyroll"],
        }
        html = componentes.render_card(t)
        assert '<span class="provider-badge highlighted">Crunchyroll</span>' in html
        assert '<span class="provider-badge">Netflix</span>' in html

    def test_card_multiplos_generos_destacados_ganham_highlighted_todos(self):
        t = {
            **BASE_TITLE,
            "genres": ["Drama", "Terror", "Comédia"],
            "highlighted_genres": ["terror", "comédia"],
        }
        html = componentes.render_card(t)
        assert '<span class="genre highlighted">Terror</span>' in html
        assert '<span class="genre highlighted">Comédia</span>' in html
        assert '<span class="genre">Drama</span>' in html

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

    def test_card_com_poster_meta_line_so_tem_data_e_tipo(self):
        # BASE_TITLE tem poster_url — nota sai da meta-line e vai pra imagem (ver
        # TestRenderCardComPoster), então a meta-line fica só com data · tipo.
        html = componentes.render_card(BASE_TITLE)
        assert 'class="meta-row meta-line"' in html
        assert "Maio de 1980 · filme" in html
        assert 'class="vital vital-rating"' not in html

    def test_card_meta_line_usa_ano_quando_sem_release_date(self):
        t = {**BASE_TITLE, "release_date": None}
        html = componentes.render_card(t)
        assert "(1980) · filme" in html

    def test_card_trailer_fica_na_linha_da_sinopse_nao_na_meta_line(self):
        # Trailer e sinopse são as duas ações de "quero saber mais" do card — dividem a
        # mesma linha em vez do trailer competir com data/tipo na meta-line.
        t = {**BASE_TITLE, "trailer_url": "https://youtube.com/watch?v=abc123"}
        html = componentes.render_card(t)
        meta_line_pos = html.index('class="meta-row meta-line"')
        meta_line_end = html.index("</div>", meta_line_pos)
        assert "vital-trailer" not in html[meta_line_pos:meta_line_end]
        synopsis_row_pos = html.index('class="meta-row synopsis-row"')
        trailer_pos = html.index("vital-trailer")
        assert synopsis_row_pos < trailer_pos

    def test_card_trailer_e_sinopse_ficam_na_mesma_linha(self):
        t = {**BASE_TITLE, "trailer_url": "https://youtube.com/watch?v=abc123"}
        html = componentes.render_card(t)
        assert 'class="meta-row synopsis-row"' in html
        synopsis_row_pos = html.index('class="meta-row synopsis-row"')
        synopsis_row_end = html.index("</div>", synopsis_row_pos)
        row = html[synopsis_row_pos:synopsis_row_end]
        assert "synopsis-label" in row
        assert "vital-trailer" in row
        label_pos = row.index("synopsis-label")
        trailer_pos = row.index("vital-trailer")
        assert label_pos < trailer_pos  # sinopse à esquerda, trailer à direita

    def test_card_trailer_sem_sinopse_ainda_gera_linha(self):
        # overview ausente: sem label/accordion de sinopse, mas o trailer não pode sumir
        t = {
            **BASE_TITLE,
            "overview": None,
            "trailer_url": "https://youtube.com/watch?v=abc123",
        }
        html = componentes.render_card(t)
        assert "synopsis-toggle" not in html
        assert 'class="meta-row synopsis-row"' in html
        assert "vital-trailer" in html

    def test_card_providers_row_nunca_contem_trailer(self):
        for t in (
            {**BASE_TITLE, "trailer_url": "https://youtube.com/watch?v=abc123"},
            {**TITLE_SEM_POSTER, "trailer_url": "https://youtube.com/watch?v=abc123"},
        ):
            html = componentes.render_card(t)
            assert "trailer-providers-row" not in html
            providers_row_pos = html.index('class="meta-row providers-row"')
            providers_row_end = html.index("</div>", providers_row_pos)
            assert "vital-trailer" not in html[providers_row_pos:providers_row_end]
            assert '<span class="provider-badge">Netflix</span>' in html

    def test_card_com_poster_duracao_fica_na_meta_line(self):
        # Com pôster, duração entra na mesma linha de data/tipo em vez de linha própria —
        # medido via Playwright que até o pior caso plausível (série com "3 temps · 24
        # eps · ~45 min/ep") cabe numa linha só na largura mínima garantida do card.
        # duration-row nem chega a ser gerada nesse caso (meio solto, ver principal.css).
        html = componentes.render_card(BASE_TITLE)
        assert "duration-row" not in html
        meta_line_pos = html.index('class="meta-row meta-line"')
        meta_line_end = html.index("</div>", meta_line_pos)
        assert "2h 26min" in html[meta_line_pos:meta_line_end]
        assert "⏱" in html[meta_line_pos:meta_line_end]

    def test_card_sem_poster_duracao_continua_em_linha_propria(self):
        # Sem pôster a meta-line já carrega classificação etária + nota — testado que
        # juntar duração ali nessas condições estoura a largura e quebra linha, então
        # continua na própria linha só nesse caso.
        html = componentes.render_card(TITLE_SEM_POSTER)
        duration_row_pos = html.index('class="meta-row duration-row"')
        duration_row_end = html.index("</div>", duration_row_pos)
        assert "2h 26min" in html[duration_row_pos:duration_row_end]
        assert "⏱" in html[duration_row_pos:duration_row_end]

    def test_card_sem_duracao_nao_gera_icone(self):
        t = {**BASE_TITLE, "duration": None}
        html = componentes.render_card(t)
        assert "⏱" not in html

    def test_card_meta_line_omite_nota_ausente(self):
        t = {**BASE_TITLE, "rating": None}
        html = componentes.render_card(t)
        assert "★" not in html
        assert "meta-line" in html

    def test_card_sem_data_tipo_nota_duracao_gera_meta_line_vazia(self):
        # A div de meta-line continua existindo mesmo sem conteúdo (diferente de
        # duration-row/cinema-row/row-people, que só aparecem quando têm o que mostrar).
        t = {
            **BASE_TITLE,
            "rating": None,
            "release_date": None,
            "year": "",
            "type": "",
            "duration": None,
        }
        html = componentes.render_card(t)
        assert 'class="meta-row meta-line"' in html
        assert '<span class="meta-info"></span>' in html

    def test_card_com_poster_duracao_sem_data_tipo_ainda_aparece_na_meta_line(self):
        # Com pôster, duração é mostrada na meta-line mesmo sem data/tipo — o ícone ⏱
        # rotula ela sozinho, .meta-info não fica vazio só porque falta o outro campo.
        t = {**BASE_TITLE, "release_date": None, "year": "", "type": ""}
        html = componentes.render_card(t)
        assert "2h 26min" in html
        meta_line_pos = html.index('class="meta-row meta-line"')
        meta_line_end = html.index("</div>", meta_line_pos)
        assert "⏱" in html[meta_line_pos:meta_line_end]

    def test_card_sem_duracao_nao_gera_duration_row(self):
        # Sem duração, a div nem é gerada (meio solto, ver principal.css) — diferente de
        # meta-line, que é sempre emitida mesmo vazia.
        t = {**BASE_TITLE, "duration": None}
        html = componentes.render_card(t)
        assert "duration-row" not in html

    def test_card_exibe_motivo(self):
        t = {**BASE_TITLE, "reason": "Nota alta e mesmo gênero pedido."}
        html = componentes.render_card(t)
        assert "Nota alta e mesmo gênero pedido." in html
        assert 'class="reason"' in html

    def test_card_sem_motivo_nao_gera_paragrafo_vazio(self):
        html = componentes.render_card(BASE_TITLE)
        assert 'class="reason"' not in html

    def test_card_motivo_sem_toggle(self):
        # Motivo é limitado a 90 caracteres na origem (prompt do agente), cabendo sem clamp
        # — sem checkbox hack de "Ver mais/Ver menos" (diferente de sinopse, que continua
        # com accordion próprio).
        t = {**BASE_TITLE, "reason": "Nota alta e mesmo gênero pedido."}
        html = componentes.render_card(t)
        assert "reason-toggle" not in html
        assert "reason-more-label" not in html
        assert "Ver mais" not in html
        assert "Ver menos" not in html

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

    def test_card_sinopse_fica_recolhida_por_padrao(self):
        html = componentes.render_card(BASE_TITLE)
        assert "Sinopse" in html
        assert 'class="synopsis-toggle"' in html
        assert BASE_TITLE["overview"] in html  # texto existe no DOM, mas fica oculto até expandir

    def test_card_sinopse_recolhida_independe_do_tamanho(self):
        # accordion recolhe a sinopse inteira por padrão, sem truncar por tamanho
        sinopse_longa = "Um escritor enlouquece num hotel isolado. " * 10
        t = {**BASE_TITLE, "overview": sinopse_longa}
        html = componentes.render_card(t)
        assert sinopse_longa in html
        assert "…" not in html  # não trunca mais o texto

    def test_card_sinopse_ausente_nao_gera_accordion(self):
        t = {**BASE_TITLE, "overview": None}
        html = componentes.render_card(t)
        assert "Sinopse" not in html
        assert "synopsis-toggle" not in html

    def test_card_toggle_id_usa_indice(self):
        html = componentes.render_card(BASE_TITLE, idx=3)
        assert 'id="synopsis-toggle-3"' in html
        assert 'for="synopsis-toggle-3"' in html

    def test_card_ficha_tecnica_fica_recolhida_por_padrao(self):
        t = {**BASE_TITLE, "director": "Stanley Kubrick", "cast": "Jack Nicholson, Shelley Duvall"}
        html = componentes.render_card(t)
        assert "Ficha Técnica" in html
        assert 'class="people-toggle"' in html
        assert "<strong>Diretor:</strong> Stanley Kubrick" in html
        assert "<strong>Elenco:</strong> Jack Nicholson, Shelley Duvall" in html

    def test_card_ficha_tecnica_tem_icone_de_grupo(self):
        t = {**BASE_TITLE, "director": "Stanley Kubrick"}
        html = componentes.render_card(t)
        assert 'class="people-icon">👥</span>' in html

    def test_card_ficha_tecnica_so_com_diretor(self):
        t = {**BASE_TITLE, "director": "Stanley Kubrick", "cast": None}
        html = componentes.render_card(t)
        assert "Ficha Técnica" in html
        assert "<strong>Diretor:</strong> Stanley Kubrick" in html
        assert "Elenco:" not in html

    def test_card_ficha_tecnica_so_com_elenco(self):
        t = {**BASE_TITLE, "director": None, "cast": "Jack Nicholson, Shelley Duvall"}
        html = componentes.render_card(t)
        assert "Ficha Técnica" in html
        assert "Diretor:" not in html
        assert "<strong>Elenco:</strong> Jack Nicholson, Shelley Duvall" in html

    def test_card_ficha_tecnica_traz_todos_os_papeis(self):
        t = {
            **BASE_TITLE,
            "director": "Stanley Kubrick",
            "cast": "Jack Nicholson, Shelley Duvall",
            "writers": "Diane Johnson",
            "composer": "Wendy Carlos",
            "producer": "Stanley Kubrick",
            "cinematographer": "John Alcott",
            "editor": "Ray Lovejoy",
            "creators": None,
        }
        html = componentes.render_card(t)
        assert "<strong>Diretor:</strong> Stanley Kubrick" in html
        assert "<strong>Elenco:</strong> Jack Nicholson, Shelley Duvall" in html
        assert "<strong>Roteiro:</strong> Diane Johnson" in html
        assert "<strong>Trilha sonora:</strong> Wendy Carlos" in html
        assert "<strong>Produção:</strong> Stanley Kubrick" in html
        assert "<strong>Fotografia:</strong> John Alcott" in html
        assert "<strong>Montagem:</strong> Ray Lovejoy" in html

    def test_card_ficha_tecnica_so_com_roteiro_gera_accordion(self):
        t = {**BASE_TITLE, "director": None, "cast": None, "writers": "Diane Johnson"}
        html = componentes.render_card(t)
        assert "Ficha Técnica" in html
        assert "<strong>Roteiro:</strong> Diane Johnson" in html

    def test_card_diretor_e_criadores_aparecem_como_bullets_separados(self):
        t = {**BASE_TITLE, "director": "Stanley Kubrick", "creators": "Duffer Brothers", "cast": None}
        html = componentes.render_card(t)
        assert "<strong>Diretor:</strong> Stanley Kubrick" in html
        assert "<strong>Criador(es):</strong> Duffer Brothers" in html

    def test_card_ficha_tecnica_ausente_nao_gera_accordion(self):
        t = {
            **BASE_TITLE,
            "director": None,
            "cast": None,
            "creators": None,
            "writers": None,
            "composer": None,
            "producer": None,
            "cinematographer": None,
            "editor": None,
        }
        html = componentes.render_card(t)
        assert "Ficha Técnica" not in html
        assert "people-toggle" not in html
        assert "row-people" not in html

    def test_card_people_toggle_id_usa_indice(self):
        t = {**BASE_TITLE, "director": "Stanley Kubrick"}
        html = componentes.render_card(t, idx=3)
        assert 'id="people-toggle-3"' in html
        assert 'for="people-toggle-3"' in html

    def test_card_ficha_tecnica_escapa_xss(self):
        t = {**BASE_TITLE, "director": '<script>alert("xss")</script>'}
        html = componentes.render_card(t)
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_card_ficha_tecnica_fica_antes_da_sinopse(self):
        t = {**BASE_TITLE, "director": "Stanley Kubrick"}
        html = componentes.render_card(t)
        people_pos = html.index('class="row-people"')
        synopsis_pos = html.index('class="row-synopsis"')
        assert people_pos < synopsis_pos

    def test_card_sinopse_fica_dentro_do_card_footer(self):
        # .card-footer (margin-top:auto, ver principal.css) empurra sinopse/trailer pra
        # mesma borda inferior nos 3 cards da fileira — só a sinopse entra nesse rodapé
        # fixo, a Ficha Técnica fica fora (faz parte do meio solto, sempre antes do rodapé
        # no HTML).
        t = {**BASE_TITLE, "director": "Stanley Kubrick"}
        html = componentes.render_card(t)
        footer_pos = html.index('class="card-footer"')
        assert "row-synopsis" in html[footer_pos:]
        assert "row-people" not in html[footer_pos:]

    def test_card_sem_sinopse_nem_trailer_nao_gera_card_footer(self):
        t = {**BASE_TITLE, "overview": None, "trailer_url": None}
        html = componentes.render_card(t)
        assert "card-footer" not in html


class TestRenderCardComPoster:
    """Com pôster (backdrop_url/poster_url), nota e classificação etária ficam sobrepostas
    na imagem em vez de disputar espaço com data/tipo no corpo do card."""

    def test_imagem_fica_dentro_de_card_media(self):
        html = componentes.render_card(BASE_TITLE)
        assert 'class="card-media"' in html
        assert 'class="media-scrim"' in html

    def test_nota_vira_rating_chip_sobre_a_imagem(self):
        html = componentes.render_card(BASE_TITLE)
        assert 'class="rating-chip"' in html
        assert "★ 8.4" in html
        assert 'class="vital vital-rating"' not in html

    def test_nota_fica_a_esquerda_e_classificacao_a_direita(self):
        # .media-badges-top usa justify-content: space-between — a ordem no HTML
        # determina esquerda/direita, nota primeiro.
        t = {**BASE_TITLE, "certification": "16"}
        html = componentes.render_card(t)
        rating_pos = html.index("rating-chip")
        certification_pos = html.index("certification-badge")
        assert rating_pos < certification_pos

    def test_classificacao_fica_dentro_de_media_badges_top(self):
        t = {**BASE_TITLE, "certification": "16"}
        html = componentes.render_card(t)
        media_badges_pos = html.index('class="media-badges-top"')
        certification_pos = html.index("certification-badge")
        card_body_pos = html.index('class="card-body"')
        assert media_badges_pos < certification_pos < card_body_pos

    def test_sem_nota_nem_classificacao_nao_gera_media_badges_vazio(self):
        t = {**BASE_TITLE, "rating": None, "certification": None}
        html = componentes.render_card(t)
        assert "media-badges-top" not in html


class TestRenderCardSemPoster:
    """Sem pôster não há onde sobrepor nota/classificação, então o card cai no layout
    anterior: badges na meta-row, trailer junto dos provedores."""

    def test_nao_gera_card_media(self):
        html = componentes.render_card(TITLE_SEM_POSTER)
        assert "card-media" not in html
        assert "<img" not in html

    def test_nota_continua_na_meta_line(self):
        html = componentes.render_card(TITLE_SEM_POSTER)
        assert 'class="vital vital-rating"' in html
        assert "★ 8.4" in html
        assert "rating-chip" not in html

    def test_classificacao_continua_na_meta_line(self):
        t = {**TITLE_SEM_POSTER, "certification": "16"}
        html = componentes.render_card(t)
        meta_line_pos = html.index('class="meta-row meta-line"')
        certification_pos = html.index("certification-badge")
        assert meta_line_pos < certification_pos


class TestRenderGrid:
    def test_grid_vazio(self):
        html = componentes.render_grid([])
        assert "grid-titles" in html

    def test_grid_com_titulos(self):
        html = componentes.render_grid([BASE_TITLE, BASE_TITLE])
        assert html.count("card") >= 2

    def test_grid_gera_ids_de_toggle_unicos_por_indice(self):
        html = componentes.render_grid([BASE_TITLE, BASE_TITLE])
        assert "synopsis-toggle-0" in html
        assert "synopsis-toggle-1" in html

    def test_grid_gera_ids_de_people_toggle_unicos_por_indice(self):
        t = {**BASE_TITLE, "director": "Stanley Kubrick"}
        html = componentes.render_grid([t, t])
        assert "people-toggle-0" in html
        assert "people-toggle-1" in html

    def test_grid_nao_gera_posicionamento_inline_de_linha_coluna(self):
        # Sem subgrid, os cards não precisam de grid-row/grid-column inline — o grid de 3
        # colunas (.grid-titles, ver principal.css) forma as fileiras sozinho via
        # auto-placement, e align-items:stretch cuida do alinhamento entre eles.
        html = componentes.render_grid([BASE_TITLE] * 4)
        assert "grid-row" not in html
        assert "grid-column" not in html

    def test_grid_nao_declara_grid_template_rows(self):
        html = componentes.render_grid([BASE_TITLE] * 4)
        assert "grid-template-rows" not in html
