"""admin.py — painel administrativo do FilmBot (aprovação de cadastro, gestão de acesso).

Só é chamado por app.py quando st.session_state["is_admin"] é True (setado em
login.py::_render_login_form a partir de infrastructure.is_admin() no momento do
login) — este módulo não repete o gate, confia no chamador."""

import html

import streamlit as st
from src import infrastructure
from src.components import icon, load_admin_css


def render_admin_panel() -> None:
    """Renderiza o painel admin: cadastros novos (aprovar/reprovar) e usuários já
    aprovados (revogar/restaurar acesso)."""
    load_admin_css()

    st.markdown(
        f'<div class="header-brand">'
        f'<span class="header-icon-badge">{icon("users", size=20)}</span>'
        f'<p class="page-title">Painel Admin</p>'
        f'</div>'
        f'<p class="header-subtitle">Aprovação de cadastro e gestão de acesso</p>',
        unsafe_allow_html=True,
    )

    _render_pending_section()
    _render_active_section()


def _render_pending_section() -> None:
    pending = infrastructure.list_pending_users()

    st.markdown('<div class="admin-section">', unsafe_allow_html=True)
    st.markdown('<p class="admin-section-title">Cadastros novos</p>', unsafe_allow_html=True)

    if not pending:
        st.markdown(
            '<p class="admin-empty">Nenhum cadastro aguardando aprovação.</p>',
            unsafe_allow_html=True,
        )
    else:
        for user in pending:
            _render_user_row(user, status_html="")
            col_approve, col_reject, _ = st.columns([1, 1, 3])
            with col_approve:
                if st.button("Aprovar", key=f"btn_aprovar_{user['email']}", use_container_width=True):
                    infrastructure.approve_signup(user["email"])
                    st.rerun()
            with col_reject:
                if st.button("Reprovar", key=f"btn_reprovar_{user['email']}", use_container_width=True):
                    infrastructure.reject_signup(user["email"])
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


def _render_active_section() -> None:
    active = infrastructure.list_active_users()

    st.markdown('<div class="admin-section">', unsafe_allow_html=True)
    st.markdown('<p class="admin-section-title">Usuários ativos</p>', unsafe_allow_html=True)

    if not active:
        st.markdown(
            '<p class="admin-empty">Nenhum cadastro aprovado ainda.</p>',
            unsafe_allow_html=True,
        )
    else:
        for user in active:
            status_html = (
                '<span class="admin-user-status active">Ativo</span>'
                if user["enabled"]
                else '<span class="admin-user-status revoked">Acesso revogado</span>'
            )
            _render_user_row(user, status_html=status_html)
            col_action, _ = st.columns([1, 4])
            with col_action:
                if user["enabled"]:
                    if st.button("Revogar", key=f"btn_revogar_{user['email']}", use_container_width=True):
                        infrastructure.revoke_access(user["email"])
                        st.rerun()
                elif st.button("Restaurar", key=f"btn_restaurar_{user['email']}", use_container_width=True):
                    infrastructure.restore_access(user["email"])
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


def _render_user_row(user: dict, *, status_html: str) -> None:
    name = html.escape(user["name"])
    email = html.escape(user["email"])
    st.markdown(
        f'<div class="admin-user-row">'
        f'<div class="admin-user-info">'
        f'<span class="admin-user-name">{name}</span>{status_html}<br/>'
        f'<span class="admin-user-email">{email}</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )
