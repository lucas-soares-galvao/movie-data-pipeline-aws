"""login.py — telas de autenticação do FilmBot (login, cadastro, esqueci a senha)."""

import re
import time

import streamlit as st
from botocore.exceptions import ClientError
from src import infrastructure
from src.components import (
    icon,
    load_countdown_script,
    load_login_button_toggle_script,
    load_login_css,
    load_password_requirements_gate_script,
    render_feedback,
    render_login_footer,
    render_password_requirements,
)
from src.infrastructure import (
    events_in_window,
    seconds_until_available,
)

_MAX_LOGIN_ATTEMPTS = 3
_LOGIN_LOCKOUT_SECONDS = 60
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@st.cache_resource
def _create_login_attempt_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de tentativas de login incorretas por IP."""
    return {}


_login_attempt_history = _create_login_attempt_history()

_MAX_RESEND_ATTEMPTS = 1
_RESEND_LOCKOUT_SECONDS = 60


@st.cache_resource
def _create_reset_attempt_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de envio/reenvio de código de reset de senha por IP."""
    return {}


_reset_attempt_history = _create_reset_attempt_history()


def _validate_password(password: str) -> str:
    """Valida a senha contra a mesma política configurada no Cognito (infra/lightsail_ia.tf:
    aws_cognito_user_pool.filmbot.password_policy), mais o teto de 16 caracteres — regra só
    do app, o Cognito não impõe máximo — checar aqui evita disparar a chamada só para
    receber InvalidPasswordException. Retorna "" se válida, senão a mensagem de erro."""
    if len(password) < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    if len(password) > 16:
        return "A senha pode ter no máximo 16 caracteres."
    if not re.search(r"[a-z]", password):
        return "A senha precisa ter pelo menos uma letra minúscula."
    if not re.search(r"[A-Z]", password):
        return "A senha precisa ter pelo menos uma letra maiúscula."
    if not re.search(r"\d", password):
        return "A senha precisa ter pelo menos um número."
    if not re.search(r"[^\w\s]", password):
        return "A senha precisa ter pelo menos um símbolo (ex: ! @ # $)."
    return ""


def render_login(client_ip: str) -> None:
    """Renderiza a tela de autenticação ativa (login, cadastro ou esqueci a senha) e
    interrompe a execução do script (`st.stop()`) se o usuário ainda não estiver
    autenticado. Se já autenticado, retorna sem efeito.

    A view ativa (`st.session_state["auth_view"]`) troca o conteúdo dentro do mesmo
    app.py, sem multipage do Streamlit — evita vazar a existência da tela de admin (ou
    de qualquer view) na barra lateral/URL para quem ainda não fez login (ver
    lightsail_ia.md)."""
    if st.session_state.get("authenticated"):
        return

    load_login_css()

    view = st.session_state.get("auth_view", "login")
    if view == "signup":
        _render_signup()
    elif view == "signup_success":
        _render_signup_success()
    elif view == "forgot_password":
        _render_forgot_password(client_ip)
    else:
        _render_login_form(client_ip)

    st.stop()


def _switch_view(view: str) -> None:
    st.session_state["auth_view"] = view
    st.rerun()


def _brand_header(subtitle: str) -> None:
    st.markdown(f"""
    <div class="login-brand">
      <span class="login-icon-badge">{icon("clapperboard", size=18)}</span>
      <p class="login-title">FilmBot</p>
    </div>
    <p class="login-subtitle">{subtitle}</p>
    """, unsafe_allow_html=True)


def _render_login_form(client_ip: str) -> None:
    _failed_attempts = events_in_window(_login_attempt_history, client_ip, _LOGIN_LOCKOUT_SECONDS)
    _locked_out = _failed_attempts >= _MAX_LOGIN_ATTEMPTS

    with st.container(key="login-card"):
        _brand_header("Seu assistente de filmes e séries com IA")

        email = st.text_input(
            "", placeholder="E-mail", label_visibility="collapsed", key="login_email"
        )
        password = st.text_input(
            "", placeholder="Senha", type="password",
            label_visibility="collapsed", key="login_password",
        )
        error_placeholder = st.empty()
        submit = st.button(
            "Entrar →", use_container_width=True, key="btn_entrar", disabled=_locked_out,
        )
        load_login_button_toggle_script(_locked_out, button_key="btn_entrar")

        if _locked_out:
            _seconds = seconds_until_available(_login_attempt_history, client_ip, _LOGIN_LOCKOUT_SECONDS)
            with error_placeholder:
                render_feedback(
                    "warning",
                    "Muitas tentativas incorretas. Tente novamente em",
                    extra_html=' <span class="time-countdown" id="countdown"></span>.',
                )
            load_countdown_script(_seconds)
        elif submit and email and password:
            result = infrastructure.authenticate(email, password)
            if result == "ok":
                st.session_state["authenticated"] = True
                st.session_state["user_email"] = email
                st.session_state["is_admin"] = infrastructure.is_admin(email)
                st.rerun()
            elif result == "pending":
                with error_placeholder:
                    render_feedback(
                        "warning", "Seu cadastro ainda está aguardando aprovação do admin."
                    )
            else:
                _login_attempt_history.setdefault(client_ip, []).append(time.time())
                if events_in_window(_login_attempt_history, client_ip, _LOGIN_LOCKOUT_SECONDS) >= _MAX_LOGIN_ATTEMPTS:
                    st.rerun()
                with error_placeholder:
                    render_feedback("error", "E-mail ou senha incorretos.")
        elif submit:
            with error_placeholder:
                render_feedback("error", "Preencha e-mail e senha.")

        link_col1, link_col2 = st.columns(2)
        with link_col1:
            if st.button("Novo cadastro", key="btn_link_cadastro", use_container_width=True):
                _switch_view("signup")
        with link_col2:
            if st.button("Esqueci a senha", key="btn_link_esqueci", use_container_width=True):
                _switch_view("forgot_password")

        render_login_footer()


def _render_signup() -> None:
    with st.container(key="login-card"):
        _brand_header("Criar uma conta nova")

        name = st.text_input("", placeholder="Nome completo", label_visibility="collapsed", key="signup_name")
        email = st.text_input("", placeholder="E-mail", label_visibility="collapsed", key="signup_email")
        password = st.text_input(
            "", placeholder="Senha", type="password", label_visibility="collapsed", key="signup_password"
        )
        confirm_password = st.text_input(
            "", placeholder="Confirmar senha", type="password",
            label_visibility="collapsed", key="signup_confirm_password",
        )
        render_password_requirements()
        error_placeholder = st.empty()
        submit = st.button("Criar cadastro →", use_container_width=True, key="btn_cadastrar")
        load_password_requirements_gate_script(
            password_key="signup_password",
            confirm_key="signup_confirm_password",
            button_key="btn_cadastrar",
        )

        if submit:
            error = _validate_signup(name, email, password, confirm_password)
            if error:
                with error_placeholder:
                    render_feedback("error", error)
            else:
                try:
                    infrastructure.sign_up(email, password, name)
                except ClientError as exc:
                    with error_placeholder:
                        render_feedback("error", _signup_error_message(exc))
                else:
                    infrastructure.notify_new_signup(email, name)
                    _switch_view("signup_success")

        if st.button("← Voltar ao login", key="btn_link_voltar", use_container_width=True):
            _switch_view("login")

        render_login_footer()


def _validate_signup(name: str, email: str, password: str, confirm_password: str) -> str:
    """Validações client-side do formulário de cadastro. Retorna "" se tudo válido,
    senão a primeira mensagem de erro encontrada."""
    if not name or not email or not password or not confirm_password:
        return "Preencha todos os campos."
    if not _EMAIL_RE.match(email):
        return "Digite um e-mail válido."
    if password != confirm_password:
        return "As senhas não coincidem."
    return _validate_password(password)


def _signup_error_message(exc: ClientError) -> str:
    code = exc.response["Error"]["Code"]
    if code == "UsernameExistsException":
        return "Esse e-mail já está cadastrado."
    if code == "InvalidPasswordException":
        return "Senha não atende aos requisitos mínimos de segurança."
    return "Não foi possível concluir o cadastro. Tente novamente."


def _render_signup_success() -> None:
    with st.container(key="login-card"):
        _brand_header("Cadastro enviado")
        render_feedback(
            "success",
            "Recebemos seu cadastro! O admin vai revisar os dados e confirmar o acesso — "
            "você recebe um aviso assim que puder entrar.",
        )
        if st.button("Ir para o login →", use_container_width=True, key="btn_ir_login_sucesso"):
            _switch_view("login")
        render_login_footer()


def _render_forgot_password(client_ip: str) -> None:
    step = st.session_state.get("reset_step", "request")
    if step == "confirm":
        _render_forgot_password_confirm(client_ip)
    else:
        _render_forgot_password_request(client_ip)


def _render_forgot_password_request(client_ip: str) -> None:
    with st.container(key="login-card"):
        _brand_header("Recuperar acesso")

        email = st.text_input("", placeholder="E-mail", label_visibility="collapsed", key="reset_email")
        error_placeholder = st.empty()
        submit = st.button("Enviar código →", use_container_width=True, key="btn_enviar_codigo")
        load_login_button_toggle_script(False, button_key="btn_enviar_codigo")

        if submit:
            if not _EMAIL_RE.match(email):
                with error_placeholder:
                    render_feedback("error", "Digite um e-mail válido.")
            else:
                try:
                    infrastructure.request_password_reset(email)
                except ClientError:
                    # Mesma mensagem tanto pra e-mail inexistente quanto pra erro real —
                    # não confirmar se um e-mail existe ou não (mesmo racional de
                    # prevent_user_existence_errors no app client, infra/lightsail_ia.tf).
                    pass
                _reset_attempt_history.setdefault(client_ip, []).append(time.time())
                st.session_state["reset_email_confirmed"] = email
                st.session_state["reset_step"] = "confirm"
                st.rerun()

        if st.button("← Voltar ao login", key="btn_link_voltar", use_container_width=True):
            _switch_view("login")

        render_login_footer()


def _render_forgot_password_confirm(client_ip: str) -> None:
    email = st.session_state.get("reset_email_confirmed", "")
    _resend_locked = (
        events_in_window(_reset_attempt_history, client_ip, _RESEND_LOCKOUT_SECONDS) >= _MAX_RESEND_ATTEMPTS
    )
    with st.container(key="login-card"):
        _brand_header(
            f"Enviamos um código para {email}. Confira também a pasta de spam." if email
            else "Digite o código recebido"
        )

        code = st.text_input("", placeholder="Código recebido por e-mail", label_visibility="collapsed", key="reset_code")
        password = st.text_input(
            "", placeholder="Nova senha", type="password", label_visibility="collapsed", key="reset_password"
        )
        confirm_password = st.text_input(
            "", placeholder="Confirmar nova senha", type="password",
            label_visibility="collapsed", key="reset_confirm_password",
        )
        render_password_requirements()
        error_placeholder = st.empty()
        submit = st.button("Redefinir senha →", use_container_width=True, key="btn_redefinir_senha")
        load_password_requirements_gate_script(
            password_key="reset_password",
            confirm_key="reset_confirm_password",
            button_key="btn_redefinir_senha",
        )

        if submit:
            error = _validate_reset(code, password, confirm_password)
            if error:
                with error_placeholder:
                    render_feedback("error", error)
            else:
                try:
                    infrastructure.confirm_password_reset(email, code, password)
                except ClientError as exc:
                    with error_placeholder:
                        render_feedback("error", _reset_error_message(exc))
                else:
                    st.session_state.pop("reset_step", None)
                    st.session_state.pop("reset_email_confirmed", None)
                    _switch_view("login")

        resend_placeholder = st.empty()
        if _resend_locked:
            _seconds = seconds_until_available(_reset_attempt_history, client_ip, _RESEND_LOCKOUT_SECONDS)
            with resend_placeholder:
                render_feedback(
                    "warning",
                    "Aguarde para pedir um novo código em",
                    extra_html=' <span class="time-countdown" id="resend-countdown"></span>.',
                )
            load_countdown_script(_seconds, element_id="resend-countdown")

        link_col1, link_col2 = st.columns(2)
        with link_col1:
            if st.button(
                "Reenviar código", key="btn_reenviar_codigo",
                use_container_width=True, disabled=_resend_locked,
            ):
                try:
                    infrastructure.request_password_reset(email)
                except ClientError:
                    # Mesmo racional anti-enumeration do passo 1 (request_password_reset acima).
                    pass
                _reset_attempt_history.setdefault(client_ip, []).append(time.time())
                with resend_placeholder:
                    render_feedback("success", "Novo código enviado. Confira a caixa de entrada e o spam.")
        with link_col2:
            if st.button("← Voltar ao login", key="btn_link_voltar", use_container_width=True):
                st.session_state.pop("reset_step", None)
                st.session_state.pop("reset_email_confirmed", None)
                _switch_view("login")

        render_login_footer()


def _validate_reset(code: str, password: str, confirm_password: str) -> str:
    if not code or not password or not confirm_password:
        return "Preencha todos os campos."
    if password != confirm_password:
        return "As senhas não coincidem."
    return _validate_password(password)


def _reset_error_message(exc: ClientError) -> str:
    code = exc.response["Error"]["Code"]
    if code == "CodeMismatchException":
        return "Código incorreto."
    if code == "ExpiredCodeException":
        return "Código expirado. Volte e peça um novo."
    if code == "InvalidPasswordException":
        return "Senha não atende aos requisitos mínimos de segurança."
    return "Não foi possível redefinir a senha. Tente novamente."
