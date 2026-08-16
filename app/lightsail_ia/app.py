"""app.py — Interface web do FilmBot (aplicativo Streamlit)."""

import streamlit as st
from src.cards import render_cards
from src.components import (
    icon,
    load_app_css,
    render_footer,
)
from src.infrastructure import (
    get_client_ip,
    load_filmbot_password,
    setup_cloudwatch_logging,
)
from src.login import render_login
from src.recommendation import render_recommendation

load_filmbot_password()
setup_cloudwatch_logging()

st.set_page_config(page_title="FilmBot", page_icon="🎬", layout="wide")

client_ip = get_client_ip()

render_login(client_ip)

# ==============================================================================
# PÁGINA PRINCIPAL
# ==============================================================================
load_app_css()

with st.container(key="header-row"):
    title_col, logout_col = st.columns([9, 1])
    with title_col:
        st.markdown(
            '<div class="header-brand">'
            f'<span class="header-icon-badge">{icon("clapperboard", size=20)}</span>'
            '<div class="header-text">'
            '<p class="header-title">FilmBot</p>'
            '<p class="header-subtitle">Seu assistente de filmes e séries com IA</p>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    with logout_col:
        if st.button("Sair", key="btn_sair"):
            st.session_state["authenticated"] = False
            st.rerun()

render_recommendation(client_ip)
render_cards()

render_footer()
