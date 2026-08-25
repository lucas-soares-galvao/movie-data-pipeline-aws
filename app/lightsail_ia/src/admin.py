"""admin.py — painel administrativo do FilmBot (aprovação de cadastro, gestão de acesso).

Só é chamado por app.py quando st.session_state["is_admin"] é True (setado em
login.py::_render_login_form a partir de infrastructure.is_admin() no momento do
login) — este módulo não repete o gate, confia no chamador."""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from src import infrastructure
from src.components import load_admin_css

_TABLE_COLUMNS = ["Nome", "E-mail", "Último acesso", "Admin", "Status"]


def render_admin_panel() -> None:
    """Renderiza o painel admin: uma única tabela com todos os cadastros (novos e já
    aprovados), coluna Admin (sim/não), Status (novo/ativo/revogado) e Ação (aprovar/
    reprovar cadastro novo; revogar usuário existente)."""
    load_admin_css()

    st.markdown(
        '<div class="admin-page">'
        '<p class="page-title">Painel Admin</p>'
        '</div>',
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

    with st.container(key="admin-table"):
        if not rows:
            st.markdown('<p class="admin-empty">Nenhum usuário encontrado.</p>', unsafe_allow_html=True)
        else:
            with st.container(key="admin-table-scroll"):
                st.table(_build_table_data(rows))
            _render_action_panel(rows)
            _render_dataframe_comparison(rows)


def _build_table_data(rows: list[dict]) -> list[dict]:
    return [
        {
            "Nome": row["name"],
            "E-mail": row["email"],
            "Último acesso": _format_last_login(row["last_login"]),
            "Admin": "Sim" if row["is_admin"] else "Não",
            "Status": _status_label(row),
        }
        for row in rows
    ]


def _status_label(user: dict) -> str:
    if user["kind"] == "pending":
        return "Novo"
    if user["enabled"]:
        return "Ativo"
    return "Revogado"


def _render_action_panel(rows: list[dict]) -> None:
    """Seletor de usuário + botões de ação, fora da tabela — st.table não aceita
    widgets por célula, então a ação não pode morar numa linha dela."""
    options = {row["email"]: f'{row["name"]} — {row["email"]}' for row in rows}
    col_select, col_actions = st.columns([2, 1], vertical_alignment="bottom")
    with col_select:
        selected_email = st.selectbox(
            "Usuário",
            options=list(options.keys()),
            format_func=lambda email: options[email],
            key="admin_action_select",
        )
    selected_user = next(row for row in rows if row["email"] == selected_email)
    with col_actions:
        _render_action_buttons(selected_user)


def _render_dataframe_comparison(rows: list[dict]) -> None:
    """Bloco de comparação (a pedido do usuário, pra ver ao lado da abordagem atual):
    a mesma grade via st.dataframe, com botão real dentro da célula de Ação
    (st.column_config.ButtonColumn, disponível a partir do Streamlit 1.59 — confirmado
    na versão instalada neste projeto). Ao contrário de st.table, aqui dá pra ter o
    widget de fato na célula, sem precisar de painel separado."""
    st.caption("Comparação — st.dataframe com coluna de Ação")
    # st.dataframe(key=...) não gera classe `st-key-<key>` no wrapper (diferente de
    # st.container/st.button, confirmado via Playwright) — sem esse container extra,
    # não haveria seletor estável pra escopar o CSS que esconde a toolbar/estiliza a
    # moldura (ver admin.css).
    with st.container(key="admin-dataframe-comparison"):
        st.dataframe(
            _build_dataframe_action_data(rows),
            hide_index=True,
            column_config={
                "Admin": st.column_config.TextColumn("Admin", alignment="center", width=80),
                "Status": st.column_config.TextColumn("Status", alignment="center", width=80),
                "Último acesso": st.column_config.TextColumn("Último acesso", alignment="left"),
                "Aprovar": st.column_config.ButtonColumn(
                    "Aprovar", key="admin_df_approve_click", alignment="center", width=80
                ),
                "Revogar": st.column_config.ButtonColumn(
                    "Revogar", key="admin_df_reject_revoke_click", alignment="center", width=80
                ),
            },
            key="admin_dataframe_comparison",
            row_height=33,
        )
    _handle_dataframe_action_click(rows)


def _build_dataframe_action_data(rows: list[dict]) -> list[dict]:
    # Emoji (✔️/❌) em vez de :material/check:/:material/close: — a célula do
    # ButtonColumn é canvas (glide-data-grid), não alcançável por CSS, então não dá
    # pra colorir o fundo do botão como os botões do painel acima; emoji já vem
    # colorido pela fonte do sistema, sem precisar de tema/CSS. ✔️ (sem caixa de
    # fundo) foi testado no lugar de ✅ pra bater com ❌, mas não renderiza verde
    # de forma confiável — ✅ garante a cor.
    data = _build_table_data(rows)
    for row, entry in zip(rows, data):
        entry["Aprovar"] = "✅" if row["kind"] == "pending" else None
        entry["Revogar"] = (
            "❌" if not row["is_admin"] and (row["kind"] == "pending" or row["enabled"]) else None
        )
    return data


def _handle_dataframe_action_click(rows: list[dict]) -> None:
    approve_click = st.session_state.get("admin_df_approve_click")
    reject_revoke_click = st.session_state.get("admin_df_reject_revoke_click")

    if approve_click:
        infrastructure.approve_signup(rows[approve_click["row"]]["email"])
        st.rerun()
    elif reject_revoke_click:
        user = rows[reject_revoke_click["row"]]
        if user["kind"] == "pending":
            infrastructure.reject_signup(user["email"])
        else:
            infrastructure.revoke_access(user["email"])
        st.rerun()


def _format_last_login(last_login: str) -> str:
    """Formata o ISO 8601 UTC gravado por infrastructure.record_login() em pt-BR,
    convertido para America/Sao_Paulo (DD/MM/AAAA HH:MM). "Nunca" para quem ainda
    não tem o atributo custom:last_login (cadastro anterior a esta feature, ou
    pendente que nunca completou login)."""
    if not last_login:
        return "Nunca"
    local_dt = datetime.fromisoformat(last_login).astimezone(ZoneInfo("America/Sao_Paulo"))
    return local_dt.strftime("%d/%m/%Y %H:%M")


def _render_action_buttons(user: dict) -> None:
    email = user["email"]

    with st.container(key=f"admin-action-{email}"):
        if user["kind"] == "pending":
            col_approve, col_reject = st.columns(2)
            with col_approve:
                if st.button("", icon=":material/check:", key=f"btn_aprovar_{email}"):
                    infrastructure.approve_signup(email)
                    st.rerun()
            with col_reject:
                if st.button("", icon=":material/close:", key=f"btn_reprovar_{email}"):
                    infrastructure.reject_signup(email)
                    st.rerun()
        elif user["enabled"] and not user["is_admin"]:
            if st.button("", icon=":material/close:", key=f"btn_revogar_{email}"):
                infrastructure.revoke_access(email)
                st.rerun()
        else:
            st.caption("Nenhuma ação disponível para este usuário.")
