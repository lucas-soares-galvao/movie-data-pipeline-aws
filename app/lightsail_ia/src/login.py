"""login.py — tela de autenticação do FilmBot."""

import time

import streamlit as st
from src.components import (
    icon,
    load_countdown_script,
    load_login_button_toggle_script,
    load_login_css,
    render_feedback,
    render_login_footer,
)
from src.infrastructure import (
    events_in_window,
    seconds_until_available,
)

_MAX_LOGIN_ATTEMPTS = 3
_LOGIN_LOCKOUT_SECONDS = 60


@st.cache_resource
def _create_login_attempt_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de tentativas de login incorretas por IP."""
    return {}


_login_attempt_history = _create_login_attempt_history()


def render_login(client_ip: str) -> None:
    """Renderiza a tela de login e interrompe a execução do script (`st.stop()`) se o
    usuário ainda não estiver autenticado. Se já autenticado, retorna sem efeito."""
    if st.session_state.get("authenticated"):
        return

    load_login_css()

    _failed_attempts = events_in_window(_login_attempt_history, client_ip, _LOGIN_LOCKOUT_SECONDS)
    _locked_out = _failed_attempts >= _MAX_LOGIN_ATTEMPTS

    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        with st.container(key="login-card"):
            st.markdown(f"""
            <div class="login-brand">
              <span class="login-icon-badge">{icon("clapperboard", size=18)}</span>
              <p class="login-title">FilmBot</p>
            </div>
            <p class="login-subtitle">Seu assistente de filmes e séries com IA</p>
            <hr class="login-divider">
            """, unsafe_allow_html=True)

            password = st.text_input(
                "", placeholder="Digite a senha de acesso...",
                type="password", label_visibility="collapsed",
            )
            error_placeholder = st.empty()
            submit = st.button(
                "Entrar →", use_container_width=True, key="btn_entrar",
                disabled=_locked_out,
            )
            load_login_button_toggle_script(_locked_out)

            if _locked_out:
                _seconds = seconds_until_available(_login_attempt_history, client_ip, _LOGIN_LOCKOUT_SECONDS)
                with error_placeholder:
                    render_feedback(
                        "warning",
                        "Muitas tentativas incorretas. Tente novamente em",
                        extra_html=' <span class="time-countdown" id="countdown"></span>.',
                    )
                load_countdown_script(_seconds)
            elif submit and password == st.secrets.get("auth", {}).get("password", ""):
                st.session_state["authenticated"] = True
                st.rerun()
            elif submit and password:
                _login_attempt_history.setdefault(client_ip, []).append(time.time())
                if events_in_window(_login_attempt_history, client_ip, _LOGIN_LOCKOUT_SECONDS) >= _MAX_LOGIN_ATTEMPTS:
                    st.rerun()
                with error_placeholder:
                    render_feedback("error", "Senha incorreta. Tente novamente.")

    render_login_footer()
    st.stop()
