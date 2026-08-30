"""profile.py — edição de nome/senha do próprio usuário logado (seção "Perfil" e seção
"Senha" da barra horizontal de navegação). Usado tanto pela tela solo "Meu Perfil"
(não-admin, chamada por app.py quando st.session_state["authenticated"] é True) quanto
pelo painel admin (admin.py), que reaproveita render_profile_tab/render_password_tab/
get_own_profile/render_nav_bar/render_nav_item para o próprio admin editar nome/senha
dentro do painel. Nenhum dos dois chamadores tem o gate repetido aqui — confia em quem
chama."""

import logging
import time

import streamlit as st
from botocore.exceptions import ClientError
from src import infrastructure
from src.components import (
    icon,
    load_countdown_script,
    load_password_requirements_gate_script,
    load_profile_css,
    render_feedback,
    render_password_requirements,
    validate_password,
)
from src.infrastructure import events_in_window, seconds_until_available

_MAX_REAUTH_ATTEMPTS = 3
_REAUTH_LOCKOUT_SECONDS = 60


@st.cache_resource
def _create_password_reauth_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de senha atual incorreta na
    troca de senha do perfil, por IP."""
    return {}


_password_reauth_history = _create_password_reauth_history()


def render_nav_item(scope: str, value: str, icon_name: str, label: str) -> None:
    """Um segmento da barra horizontal de navegação (ícone + rótulo), usado tanto pela
    tela "Meu Perfil" quanto pelo painel admin. `scope` isola a chave de sessão de qual
    seção está ativa (`f"{scope}_active_section"`) — as duas telas reaproveitam este
    componente sem colidir uma com a outra. Chamado por render_nav_bar, uma vez por
    coluna da barra.

    Implementado como `st.button` nativo (não `st.tabs`, ver profile.css/admin.py: a
    versão travada do Streamlit não suporta ícone por aba em st.tabs de forma
    estilizável sem depender de DOM interno não documentado). O ícone entra numa
    coluna separada (2º nível de aninhamento, dentro da coluna que render_nav_bar já
    aloca pra este item — o único aninhamento suportado pelo Streamlit) porque o
    rótulo de `st.button` não renderiza HTML/SVG cru — só assim dá pra reaproveitar o
    mesmo `icon()` usado no resto do card. O estado ativo usa `type="primary"` (vs.
    `"secondary"`); o destaque (fundo + cor do ícone) é resolvido 100% em CSS via
    `:has()` no wrapper da linha (profile.css) — não em Python — porque cobre ícone e
    rótulo juntos, apesar de viverem em colunas st.columns() irmãs sem elemento comum
    visível além dessa linha."""
    state_key = f"{scope}_active_section"
    is_active = st.session_state.get(state_key) == value
    icon_col, label_col = st.columns([1, 6], gap=None, vertical_alignment="center")
    with icon_col:
        st.markdown(icon(icon_name, size=18), unsafe_allow_html=True)
    with label_col:
        clicked = st.button(
            label,
            key=f"btn_nav_{scope}_{value}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        )
    if clicked and not is_active:
        st.session_state[state_key] = value
        st.rerun()


def render_nav_bar(scope: str, sections: list[tuple[str, str, str]]) -> None:
    """Barra horizontal de navegação (Usuários/Perfil/Senha no admin; Perfil/Senha na
    tela solo "Meu Perfil"), no topo da tela, acima do conteúdo da seção ativa —
    substitui o antigo menu vertical ao lado do conteúdo. Reaproveitada por admin.py e
    profile.py pra não duplicar o loop + a divisão em N colunas iguais entre as duas
    telas."""
    with st.container(key=f"{scope}-nav"):
        nav_cols = st.columns(len(sections), gap="small")
        for (value, icon_name, label), col in zip(sections, nav_cols):
            with col:
                render_nav_item(scope, value, icon_name, label)


# (valor de sessão, ícone, rótulo) — usada por render_nav_bar pra montar os itens do
# menu (Perfil/Senha).
_PROFILE_SECTIONS = [("perfil", "user", "Perfil"), ("senha", "lock", "Senha")]


def render_profile_panel(client_ip: str) -> None:
    """Renderiza a tela "Meu Perfil": barra horizontal (Perfil/Senha) no topo, com o
    conteúdo da seção ativa abaixo, centralizado (nome editável + e-mail somente
    leitura na seção "Perfil", troca de senha na seção "Senha")."""
    load_profile_css()

    active = st.session_state.setdefault("profile_active_section", "perfil")
    profile = get_own_profile(st.session_state.get("user_email", ""))

    with st.container(key="profile-shell"):
        st.markdown('<p class="page-title">Meu Perfil</p>', unsafe_allow_html=True)
        render_nav_bar("profile", _PROFILE_SECTIONS)

        with st.container(key="profile-card"):
            if active == "perfil":
                render_profile_tab(profile)
            else:
                render_password_tab(client_ip)


def get_own_profile(email: str) -> dict:
    """Busca nome/e-mail do usuário logado (admin.py também chama, pra pré-preencher a
    seção "Perfil" do painel admin com os dados do próprio admin)."""
    try:
        return infrastructure.get_user_profile(email)
    except ClientError:
        logging.exception("Erro ao buscar dados do perfil")
        return {"name": "", "email": email}


def render_profile_tab(profile: dict) -> None:
    # Nome/e-mail lado a lado (~50%/50%) no desktop, um embaixo do outro no mobile —
    # st.columns colapsa nativamente pro empilhado abaixo do breakpoint interno do
    # Streamlit, sem precisar de CSS de media query pra isso (ver profile.css).
    with st.container(key="profile-fields-row"):
        name_col, email_col = st.columns(2, gap="small")
        with name_col:
            name = st.text_input("Nome Completo", value=profile["name"], key="profile_name").strip()
        with email_col:
            # E-mail sempre desabilitado — a tela não permite trocar e-mail (decisão
            # do projeto: quem chega até aqui já autenticou com e-mail+senha no
            # login; trocar e-mail exigiria reautenticação/fluxo de verificação por
            # código, fora de escopo desta versão). Mostrado só como referência do
            # valor atual.
            st.text_input("E-mail", value=profile["email"], disabled=True, key="profile_email")
    error_placeholder = st.empty()

    if st.button("Salvar Perfil →", use_container_width=True, key="btn_salvar_perfil"):
        if not name:
            with error_placeholder:
                render_feedback("error", "O nome não pode ficar em branco.")
        elif name == profile["name"]:
            pass
        else:
            infrastructure.update_user_name(profile["email"], name)
            st.session_state["user_name"] = name
            with error_placeholder:
                render_feedback("success", "Perfil atualizado com sucesso.")


def render_password_tab(client_ip: str) -> None:
    _locked_out = (
        events_in_window(_password_reauth_history, client_ip, _REAUTH_LOCKOUT_SECONDS)
        >= _MAX_REAUTH_ATTEMPTS
    )

    # Campos de senha empilhados a 50% no desktop, com a lista de requisitos num
    # painel de 50% ao lado (colapsa pra 100%/100% empilhado no mobile, mesmo
    # racional de profile-fields-row acima — ver profile.css pro estilo do painel).
    with st.container(key="password-fields-row"):
        fields_col, requirements_col = st.columns(2, gap="medium")
        with fields_col:
            current_password = st.text_input(
                "Senha atual", type="password", key="profile_current_password",
            )
            new_password = st.text_input(
                "Nova senha", type="password", key="profile_new_password",
            )
            confirm_password = st.text_input(
                "Confirmar nova senha", type="password", key="profile_confirm_password",
            )
        with requirements_col:
            st.markdown(
                '<p class="password-requirements-title">Requisitos da senha</p>',
                unsafe_allow_html=True,
            )
            render_password_requirements()
    error_placeholder = st.empty()
    submit = st.button(
        "Salvar Senha →", use_container_width=True, key="btn_salvar_senha", disabled=_locked_out,
    )
    load_password_requirements_gate_script(
        password_key="profile_new_password",
        confirm_key="profile_confirm_password",
        button_key="btn_salvar_senha",
        locked_out=_locked_out,
    )

    if _locked_out:
        _seconds = seconds_until_available(_password_reauth_history, client_ip, _REAUTH_LOCKOUT_SECONDS)
        with error_placeholder:
            render_feedback(
                "warning",
                "Muitas tentativas incorretas. Tente novamente em",
                extra_html=' <span class="time-countdown" id="countdown"></span>.',
            )
        load_countdown_script(_seconds)
    elif submit:
        error = _validate_new_password(current_password, new_password, confirm_password)
        if error:
            with error_placeholder:
                render_feedback("error", error)
        else:
            email = st.session_state.get("user_email", "")
            result = infrastructure.change_password(email, current_password, new_password)
            if result != "ok":
                _password_reauth_history.setdefault(client_ip, []).append(time.time())
                with error_placeholder:
                    render_feedback("error", "Senha atual incorreta.")
            else:
                try:
                    infrastructure.record_password_update(email)
                except ClientError:
                    # Mesmo racional de record_login (forms.py): falha ao gravar o
                    # timestamp não deve travar a troca de senha do usuário — só loga.
                    logging.exception("Erro ao gravar password_updated_at")
                st.session_state.pop("profile_current_password", None)
                st.session_state.pop("profile_new_password", None)
                st.session_state.pop("profile_confirm_password", None)
                with error_placeholder:
                    render_feedback("success", "Senha atualizada com sucesso.")


def _validate_new_password(current_password: str, new_password: str, confirm_password: str) -> str:
    if not current_password or not new_password or not confirm_password:
        return "Preencha todos os campos."
    if new_password != confirm_password:
        return "As senhas não coincidem."
    return validate_password(new_password)
