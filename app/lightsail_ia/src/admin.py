"""admin.py — painel administrativo do FilmBot (aprovação de cadastro, gestão de acesso).

Só é chamado por app.py quando st.session_state["is_admin"] é True (setado em
login.py::_render_login_form a partir de infrastructure.is_admin() no momento do
login) — este módulo não repete o gate, confia no chamador."""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from src import infrastructure
from src.components import load_admin_css


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
            _render_users_dataframe(rows)


def _build_table_data(rows: list[dict]) -> list[dict]:
    return [
        {
            "Nome": row["name"],
            "E-mail": row["email"],
            "Cadastrado em": _format_datetime(row["created_at"]),
            "Atualizado em": _format_datetime(row["updated_at"]),
            "Último acesso": _format_datetime(row["last_login"]),
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


def _render_users_dataframe(rows: list[dict]) -> None:
    """Grade de usuários via st.dataframe, com botão real dentro da célula de Ação
    (st.column_config.ButtonColumn, disponível a partir do Streamlit 1.59 — confirmado
    na versão instalada neste projeto). st.table não aceita widgets por célula, então
    st.dataframe é o único jeito de ter aprovar/revogar na própria linha, sem painel
    separado."""
    # st.dataframe(key=...) não gera classe `st-key-<key>` no wrapper (diferente de
    # st.container/st.button, confirmado via Playwright) — sem esse container extra,
    # não haveria seletor estável pra escopar o CSS que esconde a toolbar/estiliza a
    # moldura (ver admin.css).
    with st.container(key="admin-dataframe"):
        st.dataframe(
            _build_dataframe_action_data(rows),
            # width="content" — o padrão ("stretch") distribui o espaço sobrando do
            # container entre as colunas, ignorando o `width` fixo do column_config
            # abaixo (confirmado visualmente: com "stretch", Admin/Status/Aprovar/
            # Revogar ficavam largas mesmo com width=60).
            width="content",
            hide_index=True,
            column_config={
                "Admin": st.column_config.TextColumn("Admin", alignment="center", width=60),
                "Status": st.column_config.TextColumn("Status", alignment="center", width=60),
                "Cadastrado em": st.column_config.TextColumn("Cadastrado em", alignment="left"),
                "Atualizado em": st.column_config.TextColumn("Atualizado em", alignment="left"),
                "Último acesso": st.column_config.TextColumn("Último acesso", alignment="left"),
                "Aprovar": st.column_config.ButtonColumn(
                    "Aprovar", key="admin_approve_click", alignment="center", width=60
                ),
                "Revogar": st.column_config.ButtonColumn(
                    "Revogar", key="admin_reject_revoke_click", alignment="center", width=60
                ),
            },
            key="admin_users_dataframe",
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
    approve_click = st.session_state.get("admin_approve_click")
    reject_revoke_click = st.session_state.get("admin_reject_revoke_click")

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


def _format_datetime(value: str) -> str:
    """Formata um timestamp ISO 8601 UTC (created_at/updated_at/last_login, ver
    infrastructure._parse_user()) em pt-BR, convertido para America/Sao_Paulo
    (DD/MM/AAAA HH:MM). "Nunca" para valor vazio — só ocorre em last_login, para
    quem ainda não tem o atributo custom:last_login (cadastro anterior a esta
    feature, ou pendente que nunca completou login)."""
    if not value:
        return "Nunca"
    local_dt = datetime.fromisoformat(value).astimezone(ZoneInfo("America/Sao_Paulo"))
    return local_dt.strftime("%d/%m/%Y %H:%M")
