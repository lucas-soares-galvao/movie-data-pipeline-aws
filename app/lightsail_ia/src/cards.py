"""cards.py — exibição dos resultados de recomendação do FilmBot."""

import streamlit as st
from src.components import load_cards_css, render_feedback, render_grid


def render_cards() -> None:
    """Lê `titles`/`search_error`/`search_completed` de `st.session_state` (escritos
    pela busca assíncrona em `recommendation.py`) e exibe o feedback ou a grid de
    resultados correspondente."""
    load_cards_css()

    titles = st.session_state.get("titles", [])
    _search_error = st.session_state.get("search_error")
    _no_results = st.session_state.get("search_completed") and not titles and not _search_error

    if _search_error or _no_results:
        with st.container(key="results-messages"):
            if _search_error:
                render_feedback(
                    "error",
                    "Algo deu errado ao buscar as recomendações. Tente novamente em instantes.",
                )
            if _no_results:
                render_feedback(
                    "warning",
                    "Não encontramos nada com essa descrição. Tente usar outras palavras ou "
                    "ser mais específico.",
                )

    if titles:
        word = "opção" if len(titles) == 1 else "opções"
        st.markdown(
            f'<hr class="results-divider">'
            f'<p class="results-heading">Encontramos {len(titles)} {word} para você!</p>',
            unsafe_allow_html=True,
        )
        st.html(render_grid(titles))
