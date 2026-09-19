from src import cards


def _patch_markdown(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        cards.st, "markdown",
        lambda content, unsafe_allow_html=False: calls.append(content),
    )
    return calls


class TestRenderCards:
    def test_sem_titulos_nao_renderiza_heading_nem_grid(self, monkeypatch):
        monkeypatch.setattr(cards.st, "session_state", {})
        calls = _patch_markdown(monkeypatch)

        cards.render_cards()

        # Só a injeção de CSS (load_cards_css) deve ter chamado st.markdown.
        assert len(calls) == 1
        assert "<style>" in calls[0]

    def test_lista_vazia_de_titulos_nao_renderiza_heading_nem_grid(self, monkeypatch):
        monkeypatch.setattr(cards.st, "session_state", {"titles": []})
        calls = _patch_markdown(monkeypatch)

        cards.render_cards()

        assert len(calls) == 1

    def test_um_titulo_usa_singular_opcao(self, monkeypatch):
        monkeypatch.setattr(cards.st, "session_state", {"titles": [{"title": "Duna"}]})
        calls = _patch_markdown(monkeypatch)

        cards.render_cards()

        assert "Encontramos 1 opção para você!" in calls[1]

    def test_varios_titulos_usa_plural_opcoes(self, monkeypatch):
        monkeypatch.setattr(
            cards.st, "session_state",
            {"titles": [{"title": "Duna"}, {"title": "Arrival"}]},
        )
        calls = _patch_markdown(monkeypatch)

        cards.render_cards()

        assert "Encontramos 2 opções para você!" in calls[1]

    def test_renderiza_um_card_por_titulo_na_grid(self, monkeypatch):
        monkeypatch.setattr(
            cards.st, "session_state",
            {"titles": [{"title": "Duna"}, {"title": "Arrival"}]},
        )
        calls = _patch_markdown(monkeypatch)

        cards.render_cards()

        grid_html = calls[2]
        assert grid_html.startswith("<div class=")
        assert grid_html.count('class="card"') == 2
        assert "Duna" in grid_html
        assert "Arrival" in grid_html

    def test_ausencia_de_titles_em_session_state_equivale_a_lista_vazia(self, monkeypatch):
        monkeypatch.setattr(cards.st, "session_state", {})
        calls = _patch_markdown(monkeypatch)

        cards.render_cards()

        assert len(calls) == 1
