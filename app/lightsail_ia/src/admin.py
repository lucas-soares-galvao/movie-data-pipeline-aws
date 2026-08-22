"""admin.py — painel administrativo do FilmBot (aprovação de cadastro, gestão de acesso).

Só é chamado por app.py quando st.session_state["is_admin"] é True (setado em
login.py::_render_login_form a partir de infrastructure.is_admin() no momento do
login) — este módulo não repete o gate, confia no chamador."""

import html

import streamlit as st
from src import infrastructure
from src.components import icon, load_admin_css

_COLUMN_RATIOS = [3, 4, 1.3, 1.6, 2]
_COLUMN_LABELS = ["Nome", "E-mail", "Admin", "Status", "Ação"]


def render_admin_panel() -> None:
    """Renderiza o painel admin: uma única tabela com todos os cadastros (novos e já
    aprovados), coluna Admin (sim/não), Status (novo/ativo/revogado) e Ação (aprovar/
    reprovar cadastro novo; revogar/restaurar usuário existente)."""
    load_admin_css()

    st.markdown(
        f'<div class="admin-page">'
        f'<div class="header-brand">'
        f'<span class="header-icon-badge">{icon("users", size=20)}</span>'
        f'<p class="page-title">Painel Admin</p>'
        f'</div>'
        f'<p class="header-subtitle">Aprovação de cadastro e gestão de acesso</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    _render_table()


def _build_rows() -> list[dict]:
    """Combina cadastros pendentes e usuários já aprovados numa lista só, marcando a
    origem de cada um (`kind`) e resolvendo a associação a admins por linha."""
    rows = []
    for user in infrastructure.list_pending_users():
        rows.append({**user, "kind": "pending"})
    for user in infrastructure.list_active_users():
        rows.append({**user, "kind": "active"})

    for row in rows:
        row["is_admin"] = infrastructure.is_admin(row["email"])

    return rows


def _render_table() -> None:
    rows = _build_rows()

    st.markdown('<div class="admin-table">', unsafe_allow_html=True)

    if not rows:
        st.markdown('<p class="admin-empty">Nenhum usuário encontrado.</p>', unsafe_allow_html=True)
    else:
        _render_header_row()
        for row in rows:
            _render_data_row(row)

    st.markdown('</div>', unsafe_allow_html=True)


def _render_header_row() -> None:
    cols = st.columns(_COLUMN_RATIOS)
    for col, label in zip(cols, _COLUMN_LABELS):
        col.markdown(f'<p class="admin-table-header-cell">{label}</p>', unsafe_allow_html=True)


def _render_data_row(user: dict) -> None:
    name = html.escape(user["name"])
    email = html.escape(user["email"])

    col_name, col_email, col_admin, col_status, col_action = st.columns(_COLUMN_RATIOS)

    col_name.markdown(f'<p class="admin-cell-name">{name}</p>', unsafe_allow_html=True)
    col_email.markdown(f'<p class="admin-cell-email">{email}</p>', unsafe_allow_html=True)
    col_admin.markdown(
        f'<p class="admin-cell-admin">{"Sim" if user["is_admin"] else "Não"}</p>',
        unsafe_allow_html=True,
    )
    col_status.markdown(_status_pill_html(user), unsafe_allow_html=True)

    with col_action:
        _render_action_buttons(user)


def _status_pill_html(user: dict) -> str:
    if user["kind"] == "pending":
        return '<span class="admin-user-status new">Novo</span>'
    if user["enabled"]:
        return '<span class="admin-user-status active">Ativo</span>'
    return '<span class="admin-user-status revoked">Revogado</span>'


def _render_action_buttons(user: dict) -> None:
    email = user["email"]

    if user["kind"] == "pending":
        col_approve, col_reject = st.columns(2)
        with col_approve:
            if st.button("", icon=":material/check:", key=f"btn_aprovar_{email}", use_container_width=True):
                infrastructure.approve_signup(email)
                st.rerun()
        with col_reject:
            if st.button("", icon=":material/close:", key=f"btn_reprovar_{email}", use_container_width=True):
                infrastructure.reject_signup(email)
                st.rerun()
    elif user["enabled"]:
        if st.button("", icon=":material/close:", key=f"btn_revogar_{email}", use_container_width=True):
            infrastructure.revoke_access(email)
            st.rerun()
    else:
        if st.button("", icon=":material/check:", key=f"btn_restaurar_{email}", use_container_width=True):
            infrastructure.restore_access(email)
            st.rerun()
