"""app.py — Interface web do FilmBot (aplicativo Streamlit)."""

import streamlit as st
from src.admin import render_admin_panel
from src.cards import render_cards
from src.components import (
    favicon_svg,
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

st.set_page_config(page_title="FilmBot", page_icon=favicon_svg(), layout="wide")

client_ip = get_client_ip()

render_login(client_ip)

# ==============================================================================
# PÁGINA PRINCIPAL
# ==============================================================================
load_app_css()

is_admin = st.session_state.get("is_admin", False)

with st.container(key="header-row"):
    # Terceira coluna só existe pra quem é admin (grupo Cognito "admins", checado no
    # login — ver login.py::_render_login_form) — não-admin nunca vê o botão nem sabe
    # que a tela de admin existe, mesmo racional de não usar multipage nativo do
    # Streamlit (que vazaria a rota na sidebar independente de permissão).
    if is_admin:
        title_col, admin_col, logout_col = st.columns([8, 1.3, 1])
    else:
        title_col, logout_col = st.columns([9, 1])
    with title_col:
        st.markdown(
            '<div class="header-brand">'
            f'<span class="header-icon-badge">{icon("clapperboard", size=20)}</span>'
            '<p class="header-title">FilmBot</p>'
            '</div>'
            '<p class="header-subtitle">Seu assistente de filmes e séries com IA</p>',
            unsafe_allow_html=True,
        )
    if is_admin:
        with admin_col:
            _label = "← App" if st.session_state.get("current_view") == "admin" else "Painel Admin"
            if st.button(_label, key="btn_toggle_admin"):
                _current = st.session_state.get("current_view", "app")
                st.session_state["current_view"] = "app" if _current == "admin" else "admin"
                st.rerun()
    with logout_col:
        if st.button("Sair", key="btn_sair"):
            # clear() (não só zerar "authenticated"): sem isso, "titles"/"search_completed"/
            # etc. escritos por recommendation.py sobrevivem no st.session_state (que persiste
            # por sessão de navegador, independente do login) e a última recomendação
            # reaparece sozinha ao logar de novo.
            st.session_state.clear()
            st.rerun()

if is_admin and st.session_state.get("current_view") == "admin":
    render_admin_panel()
else:
    render_recommendation(client_ip)
    render_cards()

render_footer()
