"""admin.py — painel administrativo do FilmBot (aprovação de cadastro, gestão de acesso,
e edição do próprio nome/senha do admin).

Só é chamado por app.py quando st.session_state["is_admin"] é True (setado em
forms.py::_render_login_form a partir de infrastructure.is_admin() no momento do
login) — este módulo não repete o gate, confia no chamador."""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from src import infrastructure
from src.components import load_admin_css, load_profile_css
from src.profile import (
    get_own_profile,
    render_nav_bar,
    render_password_tab,
    render_profile_tab,
)

# Mesmo racional de profile.py::_PROFILE_SECTIONS — uma lista só (valor, ícone, rótulo)
# usada por render_nav_bar pra montar os itens do menu.
_ADMIN_SECTIONS = [
    ("usuarios", "users", "Usuários"),
    ("perfil", "user", "Perfil"),
    ("senha", "lock", "Senha"),
]


def render_admin_panel(client_ip: str) -> None:
    """Renderiza o painel admin com barra horizontal (Usuários/Perfil/Senha) no topo e
    o conteúdo da seção ativa abaixo, centralizado: "Usuários" (tabela de cadastros,
    igual antes), "Perfil" e "Senha" (nome/senha do próprio admin — reaproveita
    render_profile_tab/render_password_tab/render_nav_bar de profile.py, mesmo
    padrão da tela "Meu Perfil" de não-admin, em vez de duplicar)."""
    load_admin_css()
    load_profile_css()

    active = st.session_state.setdefault("admin_active_section", "usuarios")

    # Wrapper único (título + nav + conteúdo, sempre 680px, ver admin-shell em
    # profile.css) — mesma largura/centralização para as 3 seções, sem exceção nem
    # ramificação por `active`: é isso que garante que a borda esquerda/direita nunca
    # pule ao trocar de aba. A tabela pode precisar de scroll horizontal interno
    # quando as 9 colunas não cabem em 680px (ver admin-dataframe em admin.css) — a
    # caixa em si não muda de largura por causa disso.
    with st.container(key="admin-shell"):
        st.markdown('<p class="page-title">Painel Admin</p>', unsafe_allow_html=True)
        render_nav_bar("admin", _ADMIN_SECTIONS)

        if active == "usuarios":
            # Sem card (é a tabela), único caso estruturalmente diferente da tela
            # "Meu Perfil" (profile.py), onde o conteúdo sempre fica dentro da borda
            # do card.
            _render_table()
        elif active == "perfil":
            with st.container(key="admin-profile-card"):
                render_profile_tab(get_own_profile(st.session_state.get("user_email", "")))
        else:
            with st.container(key="admin-password-card"):
                render_password_tab(client_ip)


def _build_rows() -> list[dict]:
    """Combina cadastros pendentes e usuários já aprovados numa lista só, marcando a
    origem de cada um (`kind`) e resolvendo a associação a admins por linha."""
    rows = []
    for user in infrastructure.list_pending_users():
        rows.append({**user, "kind": "pending"})
    for user in infrastructure.list_active_users():
        rows.append({**user, "kind": "active"})
    for user in infrastructure.list_unconfirmed_users():
        rows.append({**user, "kind": "unconfirmed"})

    for row in rows:
        row["is_admin"] = infrastructure.is_admin(row["email"])

    return rows


def _render_table() -> None:
    rows = _build_rows()

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
    if user["kind"] == "unconfirmed":
        return "Inativo"
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
                "Nome": st.column_config.TextColumn("Nome", alignment="left", width=200),
                "E-mail": st.column_config.TextColumn("E-mail", alignment="left", width=260),
                "Admin": st.column_config.TextColumn("Admin", alignment="center", width=60),
                "Status": st.column_config.TextColumn("Status", alignment="center", width=60),
                "Cadastrado em": st.column_config.TextColumn("Cadastrado em", alignment="left", width=140),
                "Atualizado em": st.column_config.TextColumn("Atualizado em", alignment="left", width=140),
                "Último acesso": st.column_config.TextColumn("Último acesso", alignment="left", width=140),
                "Aprovar": st.column_config.ButtonColumn(
                    "Aprovar", key="admin_approve_click", alignment="center", width=60
                ),
                "Revogar": st.column_config.ButtonColumn(
                    "Revogar", key="admin_reject_revoke_click", alignment="center", width=60
                ),
            },
            key="admin_users_dataframe",
            row_height=40,
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
    # admin_pending_action (não é a key de trigger do ButtonColumn) guarda a ação de
    # Reprovar/Revogar aguardando confirmação no modal. Necessário porque o valor de
    # admin_reject_revoke_click é um "trigger value" do próprio Streamlit: só fica
    # setado no rerun imediatamente disparado pelo clique, e é zerado sozinho em
    # qualquer rerun seguinte — inclusive o rerun causado pelo clique em "Confirmar"
    # dentro do modal. Por isso email/name/kind são resolvidos e copiados pra cá assim
    # que o clique original é detectado, antes do primeiro st.rerun().
    pending = st.session_state.get("admin_pending_action")
    if pending:
        _render_confirm_dialog(pending)
        return

    approve_click = st.session_state.get("admin_approve_click")
    reject_revoke_click = st.session_state.get("admin_reject_revoke_click")

    if approve_click:
        user = rows[approve_click["row"]]
        infrastructure.approve_signup(user["email"])
        infrastructure.notify_user_approved(user["email"], user["name"])
        st.rerun()
    elif reject_revoke_click:
        user = rows[reject_revoke_click["row"]]
        if user["kind"] == "pending":
            kind = "reject"
        elif user["kind"] == "unconfirmed":
            kind = "remove_unconfirmed"
        else:
            kind = "revoke"
        st.session_state["admin_pending_action"] = {
            "kind": kind,
            "email": user["email"],
            "name": user["name"],
        }
        st.rerun()


_CONFIRM_VERBOS = {
    "reject": "reprovar o cadastro de",
    "revoke": "revogar o acesso de",
    "remove_unconfirmed": "remover o cadastro não confirmado de",
}


@st.dialog("Confirmar ação", dismissible=False)
def _render_confirm_dialog(pending: dict) -> None:
    st.write(f"Tem certeza que deseja {_CONFIRM_VERBOS[pending['kind']]} **{pending['name']}** ({pending['email']})?")
    # Sem checkbox de notificação para remove_unconfirmed: o e-mail nunca foi
    # comprovadamente confirmado (é exatamente por isso que a linha existe), então
    # avisar por ele não tem a mesma garantia dos outros dois fluxos. Desmarcado por
    # padrão em Reprovar (a instância é pública — notificar todo cadastro reprovado
    # sinalizaria pra estranhos/spam que o e-mail existe e foi rejeitado) e marcado
    # por padrão em Revogar (quem já tinha acesso normalmente é conhecido, e um aviso
    # é mais educado). Ver infrastructure.py::notify_user_rejected/notify_user_revoked.
    notify = (
        st.checkbox("Notificar por e-mail", value=(pending["kind"] == "revoke"))
        if pending["kind"] != "remove_unconfirmed"
        else False
    )

    col_cancel, col_confirm = st.columns(2)
    cancelled = col_cancel.button("Cancelar", width="stretch")
    confirmed = col_confirm.button("Confirmar", type="primary", width="stretch")

    if confirmed:
        if pending["kind"] == "reject":
            infrastructure.reject_signup(pending["email"])
            if notify:
                infrastructure.notify_user_rejected(pending["email"], pending["name"])
        elif pending["kind"] == "remove_unconfirmed":
            infrastructure.reject_signup(pending["email"])
        else:
            infrastructure.revoke_access(pending["email"])
            if notify:
                infrastructure.notify_user_revoked(pending["email"], pending["name"])
        st.session_state.pop("admin_pending_action", None)
        st.rerun()
    elif cancelled:
        st.session_state.pop("admin_pending_action", None)
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
