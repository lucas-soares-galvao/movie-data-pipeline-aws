"""admin.py — painel administrativo do FilmBot (aprovação de cadastro, gestão de acesso,
e edição do próprio nome/senha do admin).

Só é chamado por app.py quando st.session_state["is_admin"] é True (setado em
forms.py::_render_login_form a partir de infrastructure.is_admin() no momento do
login) — este módulo não repete o gate, confia no chamador."""

import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from src import infrastructure
from src.components import load_admin_css, load_profile_css, render_feedback
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
    # quando as 9 colunas não cabem em 680px (ver .admin-table-wrap em
    # static/css/admin_table.css) — a caixa em si não muda de largura por causa disso.
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
    # Mensagem do resultado da última ação (Aprovar/Reprovar/Revogar/Remover), gravada
    # em admin_action_feedback por _render_confirm_dialog antes do st.rerun() que fecha
    # o modal (rerun perde variáveis locais, mesmo racional de admin_pending_action, ver
    # comentário em _queue_pending_action) — lida e descartada aqui pra aparecer uma
    # única vez, mesmo se a ação esvaziar a lista.
    feedback = st.session_state.pop("admin_action_feedback", None)
    if feedback:
        render_feedback(feedback["kind"], feedback["text"])

    rows = _build_rows()

    if not rows:
        st.markdown('<p class="admin-empty">Nenhum usuário encontrado.</p>', unsafe_allow_html=True)
    else:
        _render_users_table(rows)


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


# Larguras das colunas, em px — viram <col style="width:...db"> literal no <colgroup> da
# <table> (ver _build_table_html), únicas responsáveis pelo alinhamento entre cabeçalho e
# linhas (table-layout:fixed, admin_table.css) — diferente da versão anterior (st.columns()),
# uma <table> de verdade compartilha os mesmos tracks de coluna entre todas as linhas por
# construção do HTML, não precisa mais repetir o mesmo array em cada linha pra torcer pelo
# alinhamento. Índices 5-8 (Admin/Status/Aprovar/Revogar) ficam centralizados, o resto
# alinhado à esquerda — ver _CENTERED_COLUMNS.
_COLUMN_LABELS = [
    "Nome", "E-mail", "Cadastrado em", "Atualizado em", "Último acesso",
    "Admin", "Status", "Aprovar", "Revogar",
]
# Aprovar/Revogar em 90px (não 60) — pedido do usuário: o cabeçalho "Aprovar"/"Revogar" cortava
# ("APRO…"/"REVO…") na largura antiga. Soma total (1180) precisa bater com o min-width de
# admin_table.css (mesmo mecanismo de sempre — table-layout:fixed só respeita <col> se a table
# tiver largura mínima suficiente pra caber a soma).
_COLUMN_WEIGHTS = [200, 260, 140, 140, 140, 60, 60, 90, 90]
_CENTERED_COLUMNS = {5, 6, 7, 8}

_STATIC_DIR = Path(__file__).parent.parent / "static"


def _read_static(sub_dir: str, file_name: str) -> str:
    return (_STATIC_DIR / sub_dir / file_name).read_text(encoding="utf-8")


def _revoke_kind(row: dict) -> str:
    if row["kind"] == "pending":
        return "reject"
    if row["kind"] == "unconfirmed":
        return "remove_unconfirmed"
    return "revoke"


def _revoke_visible(row: dict) -> bool:
    return not row["is_admin"] and (row["kind"] == "pending" or row["enabled"])


def _render_users_table(rows: list[dict]) -> None:
    """Grade de usuários via st.components.v2.component() — <table> HTML real (Shadow DOM,
    sem iframe), não mais st.columns()+st.button() empilhados por linha. A versão anterior
    (DOM via st.columns()) já resolvia o problema original do st.dataframe/ButtonColumn
    (grade em <canvas>/glide-data-grid, inalcançável por CSS, sempre escura fora do tema
    claro/escuro — ver histórico em lightsail_ia.md), mas cada linha era um flexbox
    independente que só alinhava com o cabeçalho por coincidência de larguras repetidas
    (_COLUMN_WEIGHTS igual em todo st.columns()) — uma <table> de verdade garante isso
    estruturalmente via <colgroup> compartilhado. CSS custom properties (var(--overlay-*)
    etc., theme.css) atravessam a fronteira do Shadow DOM normalmente, então a tabela
    continua acompanhando o tema claro/escuro custom do app sem nenhuma ponte extra —
    confirmado num spike isolado antes desta migração."""
    table_data = _build_table_data(rows)
    html_body = _build_table_html(rows, table_data)
    css = _read_static("css", "admin_table.css")
    js = _read_static("js", "admin_table.js")

    # on_<key>_change precisa ser declarado por chave dinâmica (uma por botão possível) —
    # sem isso o componente não expõe o valor correspondente em `result` (confirmado no
    # mesmo spike). O callback em si não faz nada: só registra a chave, a leitura de fato é
    # via getattr(result, ...) logo abaixo, depois do rerun que o clique já disparou sozinho.
    on_changes: dict[str, object] = {}
    for row in rows:
        on_changes[f"on_approve_{row['email']}_change"] = lambda: None
        on_changes[f"on_revoke_{row['email']}_change"] = lambda: None

    admin_table = st.components.v2.component("admin_users_table", html=html_body, css=css, js=js)
    result = admin_table(**on_changes)

    # `result` só reflete o clique mais recente (não acumula histórico entre cliques sem
    # rerun no meio, achado do spike) — inofensivo aqui porque cada clique já dispara seu
    # próprio rerun, então só existe um clique "pendente de processar" por execução deste
    # bloco, igual ao `if st.button(...):` que essa tabela usava antes.
    for row in rows:
        email = row["email"]
        if row["kind"] == "pending" and getattr(result, f"approve_{email}", None):
            _queue_pending_action("approve", row)
        if _revoke_visible(row) and getattr(result, f"revoke_{email}", None):
            _queue_pending_action(_revoke_kind(row), row)

    pending = st.session_state.get("admin_pending_action")
    if pending:
        _render_confirm_dialog(pending)


def _build_table_html(rows: list[dict], table_data: list[dict]) -> str:
    col_tags = "".join(f'<col style="width:{weight}px">' for weight in _COLUMN_WEIGHTS)
    header_cells = "".join(
        f'<th class="{"col-center" if i in _CENTERED_COLUMNS else ""}">{html.escape(label)}</th>'
        for i, label in enumerate(_COLUMN_LABELS)
    )
    body_rows = "".join(_build_table_row_html(row, entry) for row, entry in zip(rows, table_data))
    return (
        '<div class="admin-table-wrap"><table>'
        f"<colgroup>{col_tags}</colgroup>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{body_rows}</tbody>"
        "</table></div>"
    )


def _build_table_row_html(row: dict, entry: dict) -> str:
    cells = []
    for i, label in enumerate(_COLUMN_LABELS[:7]):
        value = html.escape(str(entry[label]))
        css_class = "col-center" if i in _CENTERED_COLUMNS else ""
        cells.append(f'<td class="{css_class}" title="{value}">{value}</td>')

    email_attr = html.escape(row["email"])

    approve_btn = ""
    if row["kind"] == "pending":
        approve_btn = f'<button class="btn-approve" data-email="{email_attr}">✅</button>'
    cells.append(f'<td class="col-center">{approve_btn}</td>')

    revoke_btn = ""
    if _revoke_visible(row):
        revoke_btn = f'<button class="btn-revoke" data-email="{email_attr}">❌</button>'
    cells.append(f'<td class="col-center">{revoke_btn}</td>')

    return f"<tr>{''.join(cells)}</tr>"


def _queue_pending_action(kind: str, row: dict) -> None:
    """Grava a ação clicada em admin_pending_action e força o rerun que abre o modal de
    confirmação (_render_confirm_dialog) — st.button() já retorna True só no rerun
    imediato do clique (não persiste sozinho), por isso email/name/kind são copiados
    pra session_state aqui, antes do rerun."""
    st.session_state["admin_pending_action"] = {"kind": kind, "email": row["email"], "name": row["name"]}
    st.rerun()


_CONFIRM_VERBOS = {
    "approve": "aprovar o cadastro de",
    "reject": "reprovar o cadastro de",
    "revoke": "revogar o acesso de",
    "remove_unconfirmed": "remover o cadastro não confirmado de",
}

# (substantivo, particípio) da mensagem de feedback pós-ação — concordando com
# "cadastro"/"acesso" (masculinos), não com a pessoa, pra não depender do gênero dela.
_RESULT_LABELS = {
    "approve": ("Cadastro", "aprovado"),
    "reject": ("Cadastro", "reprovado"),
    "revoke": ("Acesso", "revogado"),
    "remove_unconfirmed": ("Cadastro não confirmado", "removido"),
}


@st.dialog("Confirmar ação", dismissible=False)
def _render_confirm_dialog(pending: dict) -> None:
    st.write(f"Tem certeza que deseja {_CONFIRM_VERBOS[pending['kind']]} **{pending['name']}** ({pending['email']})?")
    # Checkbox presente nos quatro fluxos, com o padrão dependendo do risco de cada um.
    # Marcado por padrão em Aprovar: o usuário aprovado precisa saber que já pode
    # logar, então o padrão seguro é notificar (evita o caso do admin esquecer de
    # marcar e o usuário nunca saber que foi liberado). Desmarcado por padrão nos
    # outros três (Reprovar/Revogar/remove_unconfirmed) — a instância é pública, então
    # notificar por padrão sinalizaria pra estranhos/spam que o e-mail existe e foi
    # rejeitado/revogado; fica a critério do admin marcar caso a caso. Ver
    # infrastructure.py::notify_user_approved/notify_user_rejected/notify_user_revoked.
    notify = st.checkbox("Notificar por e-mail", value=(pending["kind"] == "approve"))

    col_cancel, col_confirm = st.columns(2)
    cancelled = col_cancel.button("Cancelar", width="stretch")
    confirmed = col_confirm.button("Confirmar", type="primary", width="stretch")

    if confirmed:
        email_sent: bool | None = None
        if pending["kind"] == "approve":
            infrastructure.approve_signup(pending["email"])
            if notify:
                email_sent = infrastructure.notify_user_approved(pending["email"], pending["name"])
        elif pending["kind"] in ("reject", "remove_unconfirmed"):
            infrastructure.reject_signup(pending["email"])
            if notify:
                email_sent = infrastructure.notify_user_rejected(pending["email"], pending["name"])
        else:
            infrastructure.revoke_access(pending["email"])
            if notify:
                email_sent = infrastructure.notify_user_revoked(pending["email"], pending["name"])

        if email_sent is None:
            email_text, feedback_kind = "e-mail não enviado (opção desmarcada)", "success"
        elif email_sent:
            email_text, feedback_kind = "e-mail enviado com sucesso", "success"
        else:
            email_text, feedback_kind = "falha ao enviar o e-mail", "warning"

        subject, participle = _RESULT_LABELS[pending["kind"]]
        st.session_state["admin_action_feedback"] = {
            "kind": feedback_kind,
            "text": f"{subject} de {pending['name']} ({pending['email']}) {participle} — {email_text}.",
        }
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
