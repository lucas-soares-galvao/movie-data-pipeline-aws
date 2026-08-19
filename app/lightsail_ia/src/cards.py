"""cards.py — exibição dos resultados de recomendação do FilmBot."""

import streamlit as st
from src.components import load_cards_css, render_grid


def render_cards() -> None:
    """Lê `titles` de `st.session_state` (escrito pela busca assíncrona em
    `recommendation.py`) e exibe a grid de resultados, se houver. Erro de busca e
    "sem resultado" são renderizados em `recommendation.py` (dentro de
    `hero-actions`, perto do botão "Recomendar"), não aqui."""
    load_cards_css()

    titles = st.session_state.get("titles", [])

    if titles:
        word = "opção" if len(titles) == 1 else "opções"
        st.markdown(
            f'<p class="results-heading">Encontramos {len(titles)} {word} para você!</p>',
            unsafe_allow_html=True,
        )
        # " ".join(...split()) colapsa pra uma linha só, sem espaço redundante entre tags:
        # o HTML de render_card() é um f-string multi-linha com indentação >=4 espaços e
        # linhas em branco (seções condicionais vazias) — os dois gatilhos que fazem o
        # parser de Markdown do st.markdown (rodado antes do unsafe_allow_html) tratar
        # trechos como bloco de código em vez de HTML bruto. HTML não é sensível a espaço
        # em branco entre tags, então colapsar não muda nada visualmente.
        st.markdown(" ".join(render_grid(titles).split()), unsafe_allow_html=True)
