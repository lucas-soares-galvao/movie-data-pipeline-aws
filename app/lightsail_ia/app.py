"""app.py — Interface web do FilmBot (aplicativo Streamlit)."""

import streamlit as st
from src.admin import render_admin_panel
from src.cards import render_cards
from src.components import (
    favicon_svg,
    icon,
    load_app_css,
    load_scroll_lock_script,
    render_footer,
    theme_toggle_html,
)
from src.forms import render_forms
from src.infrastructure import (
    get_client_ip,
    load_filmbot_password,
    setup_cloudwatch_logging,
)
from src.profile import render_profile_panel
from src.recommendation import render_recommendation

load_filmbot_password()
setup_cloudwatch_logging()

st.set_page_config(page_title="FilmBot", page_icon=favicon_svg(), layout="wide")

client_ip = get_client_ip()

render_forms(client_ip)

# ==============================================================================
# PÁGINA PRINCIPAL
# ==============================================================================
load_app_css()
load_scroll_lock_script()

is_admin = st.session_state.get("is_admin", False)

with st.container(key="header-row"):
    # Logo à esquerda, toggle de tema + Painel Admin/Meu Perfil + Sair agrupados no canto
    # direito (pedido do usuário) — ver .st-key-header-row em app.css: a coluna do título
    # cresce pra empurrar as outras 3 (fixas) pro fim da linha, coladas entre si.
    # Admin vê "Painel Admin", não-admin vê "Meu Perfil" — nunca os dois juntos (pedido
    # do usuário: admin não edita o próprio perfil por esta tela). Não-admin nunca vê o
    # botão de admin nem sabe que a tela existe, mesmo racional de não usar multipage
    # nativo do Streamlit (que vazaria a rota na sidebar independente de permissão).
    if is_admin:
        title_col, toggle_col, break_col, admin_col, logout_col = st.columns([3, 0.6, 0.01, 1.3, 1])
    else:
        title_col, toggle_col, break_col, profile_col, logout_col = st.columns([3, 0.6, 0.01, 1.3, 1])
    with title_col:
        st.markdown(
            '<div class="header-brand">'
            f'<span class="header-icon-badge">{icon("clapperboard", size=20)}</span>'
            '<p class="header-title">FilmBot</p>'
            '</div>'
            '<p class="header-subtitle">Seu assistente de filmes e séries com IA</p>',
            unsafe_allow_html=True,
        )
    with toggle_col:
        st.markdown(theme_toggle_html(), unsafe_allow_html=True)
    with break_col:
        # Coluna vazia, só com esse marcador — força a quebra de linha deliberada do
        # cabeçalho em telas bem estreitas (≤435px, ver .header-row-break em app.css), sem
        # depender de onde o navegador decidiria cortar naturalmente.
        st.markdown('<div class="header-row-break"></div>', unsafe_allow_html=True)
    if is_admin:
        with admin_col:
            _label = "← App" if st.session_state.get("current_view") == "admin" else "Painel Admin"
            if st.button(_label, key="btn_toggle_admin"):
                _current = st.session_state.get("current_view", "app")
                st.session_state["current_view"] = "app" if _current == "admin" else "admin"
                st.rerun()
    else:
        with profile_col:
            _profile_label = "← App" if st.session_state.get("current_view") == "profile" else "Meu Perfil"
            if st.button(_profile_label, key="btn_toggle_profile"):
                _current = st.session_state.get("current_view", "app")
                st.session_state["current_view"] = "app" if _current == "profile" else "profile"
                st.rerun()
    with logout_col:
        if st.button("Sair", key="btn_sair"):
            # clear() (não só zerar "authenticated"): sem isso, "titles"/"search_completed"/
            # etc. escritos por recommendation.py sobrevivem no st.session_state (que persiste
            # por sessão de navegador, independente do login) e a última recomendação
            # reaparece sozinha ao logar de novo.
            st.session_state.clear()
            st.rerun()

_current_view = st.session_state.get("current_view")
if is_admin and _current_view == "admin":
    render_admin_panel(client_ip)
elif _current_view == "profile":
    render_profile_panel(client_ip)
else:
    render_recommendation(client_ip)
    render_cards()

render_footer()
