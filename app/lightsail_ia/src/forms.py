"""forms.py — telas de autenticação do FilmBot (login, cadastro, esqueci a senha)."""

import html
import logging
import re
import time

import streamlit as st
from botocore.exceptions import ClientError
from src import infrastructure
from src.components import (
    icon,
    load_countdown_script,
    load_form_button_toggle_script,
    load_forms_css,
    load_password_requirements_gate_script,
    render_email_hint,
    render_feedback,
    render_form_footer,
    render_password_requirements,
    theme_toggle_html,
    validate_password,
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

_MAX_CODE_ATTEMPTS = 3
_CODE_LOCKOUT_SECONDS = 60


@st.cache_resource
def _create_code_attempt_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de tentativas de código incorreto na redefinição de senha por IP."""
    return {}


_code_attempt_history = _create_code_attempt_history()


@st.cache_resource
def _create_signup_code_send_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de envio/reenvio do código de
    confirmação de e-mail do cadastro por IP. Separado de _reset_attempt_history (mesmo
    padrão, fluxo diferente) porque o primeiro envio não é uma ação explícita do
    usuário — acontece como efeito colateral do próprio sign_up() — e o cooldown de
    reenvio precisa começar a contar a partir desse sucesso, não de um clique em
    "reenviar" (ver _render_signup)."""
    return {}


_signup_code_send_history = _create_signup_code_send_history()


@st.cache_resource
def _create_signup_code_attempt_history() -> dict[str, list[float]]:
    """Cria dict compartilhado para rastrear timestamps de tentativas de código
    incorreto na confirmação de e-mail do cadastro por IP."""
    return {}


_signup_code_attempt_history = _create_signup_code_attempt_history()


def render_forms(client_ip: str) -> None:
    """Renderiza a tela de autenticação ativa (login, cadastro ou esqueci a senha) e
    interrompe a execução do script (`st.stop()`) se o usuário ainda não estiver
    autenticado. Se já autenticado, retorna sem efeito.

    A view ativa (`st.session_state["auth_view"]`) troca o conteúdo dentro do mesmo
    app.py, sem multipage do Streamlit — evita vazar a existência da tela de admin (ou
    de qualquer view) na barra lateral/URL para quem ainda não fez login (ver
    lightsail_ia.md)."""
    if st.session_state.get("authenticated"):
        return

    load_forms_css()

    view = st.session_state.get("auth_view", "login")
    if view == "signup":
        _render_signup(client_ip)
    elif view == "signup_resume":
        _render_signup_resume_request(client_ip)
    elif view == "signup_confirm":
        _render_signup_confirm(client_ip)
    elif view == "signup_success":
        _render_signup_success()
    elif view == "forgot_password":
        _render_forgot_password(client_ip)
    elif view == "password_reset_success":
        _render_password_reset_success()
    else:
        _render_login_form(client_ip)

    st.stop()


def _switch_view(view: str) -> None:
    st.session_state["auth_view"] = view
    st.rerun()


def _brand_header(title: str | None = None) -> None:
    st.markdown(f"""
    <div class="form-brand">
      <div class="form-brand-title">
        <span class="form-icon-badge">{icon("clapperboard", size=18)}</span>
        <p class="form-title">FilmBot</p>
      </div>
      {theme_toggle_html()}
    </div>
    <p class="form-subtitle">Seu assistente de filmes e séries com IA</p>
    """, unsafe_allow_html=True)
    if title:
        st.markdown(f'<p class="form-page-title">{title}</p>', unsafe_allow_html=True)


def _render_login_form(client_ip: str) -> None:
    _failed_attempts = events_in_window(_login_attempt_history, client_ip, _LOGIN_LOCKOUT_SECONDS)
    _locked_out = _failed_attempts >= _MAX_LOGIN_ATTEMPTS

    with st.container(key="form-card"):
        _brand_header()

        email = st.text_input(
            "E-mail", placeholder="Digite seu e-mail", key="login_email"
        )
        password = st.text_input(
            "Senha", placeholder="Digite sua senha", type="password",
            key="login_password",
        )
        error_placeholder = st.empty()
        submit = st.button(
            "Entrar →", use_container_width=True, key="btn_entrar", disabled=_locked_out,
        )
        load_form_button_toggle_script(_locked_out, button_key="btn_entrar")

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
                try:
                    st.session_state["user_name"] = infrastructure.get_user_profile(email)["name"]
                except ClientError:
                    # Falha ao buscar o nome não deve travar o login — a tela de
                    # recomendação trata user_name vazio como "sem saudação".
                    logging.exception("Erro ao buscar nome do perfil no login")
                    st.session_state["user_name"] = ""
                try:
                    infrastructure.record_login(email)
                except ClientError:
                    # Falha ao gravar o timestamp não deve travar o login do usuário —
                    # só loga, não propaga.
                    logging.exception("Erro ao gravar last_login")
                st.rerun()
            elif result == "pending":
                with error_placeholder:
                    render_feedback(
                        "warning",
                        "Seu cadastro ainda não está liberado para acesso. Confirme seu "
                        "e-mail (confira também o spam) ou aguarde a aprovação do admin.",
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

        with st.container(key="login-links-row"):
            link_col1, link_col2 = st.columns(2)
            with link_col1:
                if st.button("Esqueci a senha", key="btn_link_esqueci", use_container_width=True):
                    _switch_view("forgot_password")
            with link_col2:
                if st.button("Novo cadastro", key="btn_link_cadastro", use_container_width=True):
                    _switch_view("signup")

        render_form_footer()


def _render_password_reset_success() -> None:
    with st.container(key="form-card"):
        _brand_header("Senha Redefinida")
        render_feedback("success", "Senha redefinida com sucesso! Faça login com sua nova senha.")
        if st.button("Ir para o login →", use_container_width=True, key="btn_ir_login_reset"):
            _switch_view("login")
        render_form_footer()


def _render_signup(client_ip: str) -> None:
    with st.container(key="form-card"):
        _brand_header("Criar uma Conta Nova")

        with st.container(key="password-fields-row"):
            fields_col, requirements_col = st.columns(2, gap="medium")
            with fields_col:
                name = st.text_input(
                    "Nome Completo", placeholder="Digite seu nome completo", key="signup_name"
                ).strip()
                email = st.text_input("E-mail", placeholder="Digite seu e-mail", key="signup_email")
                render_email_hint()
                password = st.text_input(
                    "Senha", placeholder="Digite sua senha", type="password", key="signup_password"
                )
                confirm_password = st.text_input(
                    "Confirmar senha", placeholder="Digite sua senha novamente", type="password",
                    key="signup_confirm_password",
                )
            with requirements_col:
                st.markdown(
                    '<p class="password-requirements-title">Requisitos da senha</p>',
                    unsafe_allow_html=True,
                )
                render_password_requirements()
        error_placeholder = st.empty()
        submit = st.button("Criar cadastro →", use_container_width=True, key="btn_cadastrar")
        load_password_requirements_gate_script(
            password_key="signup_password",
            confirm_key="signup_confirm_password",
            button_key="btn_cadastrar",
            email_key="signup_email",
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
                    resumed = (
                        exc.response["Error"]["Code"] == "UsernameExistsException"
                        and _start_signup_resume(email, client_ip) == "ok"
                    )
                    if resumed:
                        _switch_view("signup_confirm")
                    else:
                        with error_placeholder:
                            render_feedback("error", _signup_error_message(exc))
                else:
                    # O código de confirmação já foi enviado como efeito colateral do
                    # sign_up() — marca o cooldown de reenvio a partir de agora, não de
                    # uma ação de "enviar" separada (não existe uma, ao contrário do
                    # reset de senha).
                    _signup_code_send_history.setdefault(client_ip, []).append(time.time())
                    st.session_state["signup_email_confirmed"] = email
                    st.session_state["signup_name_confirmed"] = name
                    st.session_state.pop("signup_resumed", None)
                    _switch_view("signup_confirm")

        if st.button(
            "Já iniciei um cadastro e perdi o código", key="btn_link_retomar", use_container_width=True,
        ):
            _switch_view("signup_resume")

        if st.button("← Voltar ao login", key="btn_link_voltar", use_container_width=True):
            _switch_view("login")

        render_form_footer()


def _validate_signup(name: str, email: str, password: str, confirm_password: str) -> str:
    """Validações client-side do formulário de cadastro. Retorna "" se tudo válido,
    senão a primeira mensagem de erro encontrada."""
    if not name or not email or not password or not confirm_password:
        return "Preencha todos os campos."
    if not _EMAIL_RE.match(email):
        return "Digite um e-mail válido."
    if password != confirm_password:
        return "As senhas não coincidem."
    return validate_password(password)


def _signup_error_message(exc: ClientError) -> str:
    code = exc.response["Error"]["Code"]
    if code == "UsernameExistsException":
        return "Esse e-mail já está cadastrado."
    if code == "InvalidPasswordException":
        return "Senha não atende aos requisitos mínimos de segurança."
    return "Não foi possível concluir o cadastro. Tente novamente."


def _start_signup_resume(email: str, client_ip: str) -> str:
    """Retoma um cadastro abandonado (e-mail já existe no Cognito como UNCONFIRMED —
    usuário saiu antes de digitar o código): reenvia o código (mesma chamada do botão
    "Reenviar código" de _render_signup_confirm) e prepara a tela de confirmação para
    pedir Nome/Senha novos ali, não aqui. Chamada tanto pelo link dedicado
    "Já iniciei um cadastro" (_render_signup_resume_request) quanto pelo
    UsernameExistsException de um reenvio acidental do formulário completo de cadastro
    (_render_signup) — mesmo comportamento nos dois casos.

    Retorna "ok" (reenviou ou já tinha um código válido recente, e trocou de view — o
    chamador só precisa disparar _switch_view("signup_confirm")), "not_pending" (e-mail
    não existe ou já foi confirmado — o chamador decide a mensagem, já que o racional de
    "revelar ou não" difere entre o formulário de cadastro e o link de retomada) ou
    "resend_failed" (erro real do Cognito ao reenviar).

    Não recebe nem grava senha/nome do Cognito aqui de propósito: ainda não houve nenhuma
    prova de que quem está pedindo o reenvio é o dono do e-mail (reenviar código é uma
    ação que qualquer um sabendo o e-mail alheio pode disparar). Gravar a senha antes
    disso abriria uma janela de account takeover: um atacante definiria a própria senha,
    e a vítima, ao confirmar o código real recebido por e-mail, ativaria a conta com a
    senha do atacante sem ele nunca precisar ver o código. Por isso a aplicação de fato
    (apply_resumed_signup) só acontece depois que confirm_sign_up() validar o código em
    _render_signup_confirm — a posse do código é a prova de identidade necessária, mesmo
    racional de confirm_password_reset(). O nome pré-preenchido na tela de confirmação
    vem de get_unconfirmed_signup_name() (o que já está gravado no Cognito), não do que
    foi digitado agora — evita mostrar de volta um nome que um atacante acabou de digitar
    num formulário de cadastro reenviado por engano."""
    if infrastructure.get_user_status(email) != "UNCONFIRMED":
        return "not_pending"

    _resend_locked = (
        events_in_window(_signup_code_send_history, client_ip, _RESEND_LOCKOUT_SECONDS) >= _MAX_RESEND_ATTEMPTS
    )
    if not _resend_locked:
        try:
            infrastructure.resend_confirmation_code(email)
        except ClientError:
            logging.exception("Erro ao reenviar código de cadastro incompleto")
            return "resend_failed"
        _signup_code_send_history.setdefault(client_ip, []).append(time.time())
    # Se está dentro do cooldown, não reenvia de novo (já tem um código válido recente) —
    # só leva o usuário direto pra tela de código.

    try:
        name = infrastructure.get_unconfirmed_signup_name(email)
    except (ClientError, IndexError):
        logging.exception("Erro ao buscar nome do cadastro pendente")
        name = ""

    st.session_state["signup_email_confirmed"] = email
    st.session_state["signup_name_confirmed"] = name
    st.session_state["signup_resumed"] = True
    return "ok"


def _render_signup_resume_request(client_ip: str) -> None:
    with st.container(key="form-card"):
        _brand_header("Retomar Cadastro")
        st.markdown(
            '<p class="form-subtitle">Perdeu o código de confirmação? '
            'Digite o e-mail do cadastro para receber um novo.</p>',
            unsafe_allow_html=True,
        )

        email = st.text_input("E-mail", placeholder="Digite o e-mail do cadastro", key="resume_email")
        render_email_hint()
        error_placeholder = st.empty()
        submit = st.button("Reenviar código →", use_container_width=True, key="btn_reenviar_cadastro")
        load_form_button_toggle_script(False, button_key="btn_reenviar_cadastro", email_key="resume_email")

        if submit:
            if not _EMAIL_RE.match(email):
                with error_placeholder:
                    render_feedback("error", "Digite um e-mail válido.")
            else:
                result = _start_signup_resume(email, client_ip)
                if result == "ok":
                    _switch_view("signup_confirm")
                elif result == "not_pending":
                    with error_placeholder:
                        render_feedback(
                            "error", "Não encontramos um cadastro pendente de confirmação com esse e-mail.",
                        )
                else:
                    with error_placeholder:
                        render_feedback(
                            "error", "Não foi possível reenviar o código agora. Tente novamente em instantes.",
                        )

        if st.button("← Voltar ao login", key="btn_link_voltar", use_container_width=True):
            _switch_view("login")

        render_form_footer()


def _render_signup_confirm(client_ip: str) -> None:
    email = st.session_state.get("signup_email_confirmed", "")
    name = st.session_state.get("signup_name_confirmed", "")
    resumed = st.session_state.get("signup_resumed", False)
    if resumed and st.session_state.get("signup_resume_step") == "details":
        _render_signup_resume_details(client_ip, email, name)
        return

    _code_locked_out = (
        events_in_window(_signup_code_attempt_history, client_ip, _CODE_LOCKOUT_SECONDS) >= _MAX_CODE_ATTEMPTS
    )
    with st.container(key="form-card"):
        _brand_header("Confirme seu E-mail")
        if email:
            render_feedback("success", f"Enviamos um código para {email}. Confira também a pasta de spam.")
        else:
            st.markdown('<p class="form-subtitle">Digite o código recebido</p>', unsafe_allow_html=True)

        code = st.text_input(
            "Código de confirmação", placeholder="Digite o código recebido por e-mail", key="signup_code"
        )
        error_placeholder = st.empty()
        submit = st.button(
            "Confirmar e-mail →", use_container_width=True,
            key="btn_confirmar_email", disabled=_code_locked_out,
        )
        load_form_button_toggle_script(_code_locked_out, button_key="btn_confirmar_email")

        if _code_locked_out:
            _seconds = seconds_until_available(_signup_code_attempt_history, client_ip, _CODE_LOCKOUT_SECONDS)
            with error_placeholder:
                render_feedback(
                    "warning",
                    "Muitas tentativas de código incorreto. Tente novamente em",
                    extra_html=' <span class="time-countdown" id="countdown"></span>.',
                )
            load_countdown_script(_seconds)
        elif submit:
            if not code:
                with error_placeholder:
                    render_feedback("error", "Digite o código recebido por e-mail.")
            else:
                try:
                    infrastructure.confirm_sign_up(email, code)
                except ClientError as exc:
                    if exc.response["Error"]["Code"] == "CodeMismatchException":
                        _signup_code_attempt_history.setdefault(client_ip, []).append(time.time())
                        if (
                            events_in_window(_signup_code_attempt_history, client_ip, _CODE_LOCKOUT_SECONDS)
                            >= _MAX_CODE_ATTEMPTS
                        ):
                            st.rerun()
                    with error_placeholder:
                        render_feedback("error", _signup_code_error_message(exc))
                else:
                    try:
                        infrastructure.notify_new_signup(email, name)
                    except ClientError:
                        # Mesmo racional de record_login (_render_login_form): falha ao
                        # notificar o admin não deve travar a confirmação do próprio
                        # usuário — só loga, não propaga. Chamado aqui (não só no caso
                        # não-retomado) porque a conta já vira CONFIRMED+Disabled assim
                        # que o código é validado, independente de quando a pessoa
                        # termina de preencher nome/senha na tela seguinte.
                        logging.exception("Erro ao notificar novo cadastro")
                    if resumed:
                        # Nome/senha entram só na próxima tela (_render_signup_resume_details),
                        # depois do código já validado — mesmo racional de segurança
                        # documentado em _start_signup_resume/apply_resumed_signup: a posse
                        # do código é a prova de identidade necessária antes de gravar
                        # qualquer coisa no Cognito.
                        st.session_state["signup_resume_step"] = "details"
                        st.rerun()
                    else:
                        st.session_state.pop("signup_email_confirmed", None)
                        st.session_state.pop("signup_name_confirmed", None)
                        st.session_state.pop("signup_resumed", None)
                        _switch_view("signup_success")

        @st.fragment(run_every=1)
        def _resend_section() -> None:
            # Mesmo racional de _resend_section em _render_forgot_password_confirm: recalcula
            # 1x/s a partir do tempo real decorrido, sem depender de reload de página.
            _resend_locked = (
                events_in_window(_signup_code_send_history, client_ip, _RESEND_LOCKOUT_SECONDS)
                >= _MAX_RESEND_ATTEMPTS
            )
            message: tuple[str, str] | None = None
            if _resend_locked:
                _seconds = seconds_until_available(_signup_code_send_history, client_ip, _RESEND_LOCKOUT_SECONDS)
                mm, ss = divmod(_seconds, 60)
                countdown = f"{mm:02d}:{ss:02d}"
                if st.session_state.get("signup_resend_failed", False):
                    message = (
                        "error",
                        f"Não foi possível reenviar o código agora. Tente de novo em {countdown}.",
                    )
                elif st.session_state.get("signup_code_just_resent", False):
                    message = (
                        "success",
                        "Novo código enviado. Confira a caixa de entrada e o spam. "
                        f"Aguarde {countdown} para pedir outro.",
                    )
                else:
                    message = ("warning", f"Aguarde {countdown} para pedir um novo código.")

            if message:
                render_feedback(*message)

            with st.container(key="resend-links-row"):
                link_col1, link_col2 = st.columns(2)
                with link_col1:
                    if st.button("← Voltar ao login", key="btn_link_voltar", use_container_width=True):
                        st.session_state.pop("signup_email_confirmed", None)
                        st.session_state.pop("signup_name_confirmed", None)
                        st.session_state.pop("signup_resumed", None)
                        st.session_state.pop("signup_resume_step", None)
                        _switch_view("login")
                with link_col2:
                    if st.button(
                        "Reenviar código", key="btn_reenviar_codigo", type="tertiary",
                        disabled=_resend_locked, use_container_width=True,
                    ):
                        # Diferente do reenvio de reset de senha (anti user-enumeration —
                        # ali faz sentido fingir sucesso mesmo em erro, pra não revelar se o
                        # e-mail existe), aqui o e-mail já é uma conta sabidamente existente
                        # (o próprio usuário acabou de se cadastrar com ele, exibido na tela).
                        # Engolir o erro silenciosamente escondia falhas reais do Cognito
                        # (ex.: LimitExceededException da cota própria de reenvio) atrás de
                        # uma mensagem de sucesso falsa — por isso loga e avisa o usuário.
                        try:
                            infrastructure.resend_confirmation_code(email)
                        except ClientError:
                            logging.exception("Erro ao reenviar código de confirmação de cadastro")
                            st.session_state["signup_resend_failed"] = True
                            st.session_state["signup_code_just_resent"] = False
                        else:
                            st.session_state["signup_code_just_resent"] = True
                            st.session_state.pop("signup_resend_failed", None)
                        _signup_code_send_history.setdefault(client_ip, []).append(time.time())
                        st.rerun(scope="fragment")

        _resend_section()

        render_form_footer()


def _render_signup_resume_details(client_ip: str, email: str, name: str) -> None:
    """Segunda tela do cadastro retomado, só depois do código já confirmado por
    _render_signup_confirm — Nome (editável, pré-preenchido com o que já estava gravado)
    + E-mail (fixo) + Senha + Confirmar Senha (vazios). Separada da tela de código porque,
    diferente de "Esqueci a senha" (`ConfirmForgotPassword` exige a senha nova no mesmo
    request do código — não há como o Cognito validar só o código do reset de senha),
    `ConfirmSignUp` não mexe em senha: dá pra confirmar o código de verdade antes de pedir
    qualquer campo de senha."""
    with st.container(key="form-card"):
        _brand_header("Confirme seu E-mail")
        render_feedback("success", "E-mail confirmado! Finalize preenchendo seus dados abaixo.")

        with st.container(key="password-fields-row"):
            fields_col, requirements_col = st.columns(2, gap="medium")
            with fields_col:
                name = st.text_input("Nome Completo", value=name, key="signup_resume_name").strip()
                # E-mail somente leitura — não é mais st.text_input(disabled=True): mesmo
                # problema de legibilidade em modo claro já corrigido em profile.py (ver
                # comentário lá), reaproveitando aqui o mesmo <div> estilizado via CSS
                # próprio (.readonly-field*, profile.css).
                st.markdown(
                    '<div class="readonly-field">'
                    '<label class="readonly-field-label">E-mail</label>'
                    f'<div class="readonly-field-value">{html.escape(email)}</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                password = st.text_input(
                    "Senha", placeholder="Digite sua senha", type="password", key="signup_resume_password",
                )
                confirm_password = st.text_input(
                    "Confirmar senha", placeholder="Digite sua senha novamente", type="password",
                    key="signup_resume_confirm_password",
                )
            with requirements_col:
                st.markdown(
                    '<p class="password-requirements-title">Requisitos da senha</p>',
                    unsafe_allow_html=True,
                )
                render_password_requirements()

        error_placeholder = st.empty()
        submit = st.button("Concluir cadastro →", use_container_width=True, key="btn_concluir_retomada")
        load_password_requirements_gate_script(
            password_key="signup_resume_password",
            confirm_key="signup_resume_confirm_password",
            button_key="btn_concluir_retomada",
        )

        if submit:
            error = _validate_signup_resume_details(name, password, confirm_password)
            if error:
                with error_placeholder:
                    render_feedback("error", error)
            else:
                try:
                    infrastructure.apply_resumed_signup(email, password, name)
                except ClientError:
                    logging.exception("Erro ao aplicar senha/nome do cadastro retomado")
                st.session_state.pop("signup_email_confirmed", None)
                st.session_state.pop("signup_name_confirmed", None)
                st.session_state.pop("signup_resumed", None)
                st.session_state.pop("signup_resume_step", None)
                _switch_view("signup_success")

        if st.button("← Voltar", key="btn_link_voltar_codigo", use_container_width=True):
            st.session_state["signup_resume_step"] = "code"
            st.rerun()

        render_form_footer()


def _validate_signup_resume_details(name: str, password: str, confirm_password: str) -> str:
    """Validações client-side da tela de dados finais de um cadastro retomado (Nome +
    Senha + Confirmar Senha) — mesmo formato de _validate_reset, mais o campo Nome; sem
    `code` porque ele já foi validado na tela anterior."""
    if not name or not password or not confirm_password:
        return "Preencha todos os campos."
    if password != confirm_password:
        return "As senhas não coincidem."
    return validate_password(password)


def _signup_code_error_message(exc: ClientError) -> str:
    code = exc.response["Error"]["Code"]
    if code == "CodeMismatchException":
        return "Código incorreto."
    if code == "ExpiredCodeException":
        return "Código expirado. Peça um novo código."
    if code in ("LimitExceededException", "TooManyFailedAttemptsException"):
        # Cota/lockout interno do próprio Cognito, distinto do nosso lockout de 60s
        # (_signup_code_attempt_history) — pode durar mais tempo.
        return "Muitas tentativas. Aguarde alguns minutos e tente novamente."
    if code == "AliasExistsException":
        return "Esse e-mail já está associado a outra conta confirmada."
    if code == "UserNotFoundException":
        return "Cadastro não encontrado. Refaça o cadastro."
    return "Não foi possível confirmar seu e-mail. Tente novamente."


def _render_signup_success() -> None:
    with st.container(key="form-card"):
        _brand_header("Cadastro Enviado")
        render_feedback(
            "success",
            "Recebemos seu cadastro! O admin vai revisar os dados e confirmar o acesso — "
            "você recebe um aviso assim que puder entrar.",
        )
        if st.button("Ir para o login →", use_container_width=True, key="btn_ir_login_sucesso"):
            _switch_view("login")
        render_form_footer()


def _render_forgot_password(client_ip: str) -> None:
    step = st.session_state.get("reset_step", "request")
    if step == "confirm":
        _render_forgot_password_confirm(client_ip)
    else:
        _render_forgot_password_request(client_ip)


def _render_forgot_password_request(client_ip: str) -> None:
    with st.container(key="form-card"):
        _brand_header("Recuperar Acesso")

        st.text_input("E-mail", placeholder="Digite seu e-mail", key="reset_email")
        render_email_hint()

        @st.fragment(run_every=1)
        def _send_section() -> None:
            # Rate limit compartilhado com o reenvio (_reset_attempt_history/
            # _RESEND_LOCKOUT_SECONDS em _render_forgot_password_confirm) — cobre também este
            # passo porque get_user_status() abaixo revela existência/status do e-mail (decisão
            # consciente do projeto), e list_users não tem a mesma cota nativa que protege
            # ForgotPassword/ConfirmForgotPassword no Cognito. Recalculado a cada tick do
            # fragmento (1x/s) a partir do tempo real decorrido — em vez de só uma vez por
            # rerun completo — pra que o botão fique genuinamente clicável (disabled=False do
            # ponto de vista do backend) assim que os 60s passam, mesmo sem nenhuma outra
            # interação na página. Ver load_countdown_script() em components.py: o mecanismo
            # antigo (reenable_button_key) só reabilitava o botão via DOM no navegador, sem
            # avisar o backend — o clique nunca chegava a request_password_reset().
            _send_locked = (
                events_in_window(_reset_attempt_history, client_ip, _RESEND_LOCKOUT_SECONDS) >= _MAX_RESEND_ATTEMPTS
            )
            submit = st.button(
                "Enviar código →", use_container_width=True, key="btn_enviar_codigo", disabled=_send_locked,
            )
            load_form_button_toggle_script(_send_locked, button_key="btn_enviar_codigo", email_key="reset_email")

            # Mensagem computada aqui e só renderizada uma vez, no fim, sem st.empty(): um
            # placeholder recriado a cada tick (run_every=1) e preenchido logo em seguida vira
            # duas escritas separadas (uma "limpa o slot", outra "preenche") — o Streamlit às
            # vezes manda essas duas atualizações em frames distintos pro navegador, piscando
            # a mensagem por ~200ms a cada segundo (medido via poll de 50ms no DOM). Um único
            # elemento condicional, na mesma posição do script em todo tick, atualiza no lugar
            # sem esse "clear" intermediário — mesmo padrão já usado pelo st.button acima, que
            # nunca piscou.
            message: tuple[str, str] | None = None

            if _send_locked:
                _seconds = seconds_until_available(_reset_attempt_history, client_ip, _RESEND_LOCKOUT_SECONDS)
                mm, ss = divmod(_seconds, 60)
                countdown = f"{mm:02d}:{ss:02d}"
                # .get() (não .pop()) — o fragmento se auto-atualiza a cada 1s (run_every=1)
                # durante todo o cooldown, e popar a flag no primeiro desses re-renders a
                # apagaria quase instantaneamente, substituída pelo aviso genérico de
                # contagem regressiva no tick seguinte. A flag some sozinha porque cada novo
                # envio já reescreve as duas para o valor correto (True/False) antes de
                # qualquer rerun (ver `elif submit` abaixo).
                if st.session_state.get("email_not_registered", False):
                    message = (
                        "error",
                        "Esse e-mail ainda não tem cadastro. Crie uma conta para continuar, "
                        f"ou tente outro e-mail em {countdown}.",
                    )
                elif st.session_state.get("email_pending_approval", False):
                    message = ("warning", "Seu cadastro ainda está aguardando aprovação do admin.")
                else:
                    message = ("warning", f"Aguarde para tentar novamente em {countdown}.")
            elif submit:
                # Lido via session_state (não pela variável local `email` do escopo externo):
                # um clique aqui dentro dispara rerun só do fragmento, que não reexecuta o
                # st.text_input() de fora — a variável fechada por closure poderia estar
                # desatualizada se o usuário editasse o campo sem sair do fragmento.
                current_email = st.session_state.get("reset_email", "")
                if not _EMAIL_RE.match(current_email):
                    message = ("error", "Digite um e-mail válido.")
                else:
                    status = infrastructure.get_user_status(current_email)
                    # Sempre reescreve as duas flags (nunca só a que deu True) — sem isso, uma
                    # flag deixada True por uma tentativa anterior (outro e-mail, outro cooldown)
                    # vazaria pro aviso desta tentativa, já que agora elas não são mais
                    # consumidas por pop() no render acima.
                    st.session_state["email_not_registered"] = status is None
                    st.session_state["email_pending_approval"] = status == "UNCONFIRMED"
                    if status is None:
                        _reset_attempt_history.setdefault(client_ip, []).append(time.time())
                        st.rerun(scope="fragment")
                    elif status == "UNCONFIRMED":
                        _reset_attempt_history.setdefault(client_ip, []).append(time.time())
                        st.rerun(scope="fragment")
                    else:
                        try:
                            infrastructure.request_password_reset(current_email)
                        except ClientError:
                            # Erro real do Cognito depois que já confirmamos o status do e-mail
                            # (get_user_status acima) — não expor detalhe interno ao usuário.
                            pass
                        _reset_attempt_history.setdefault(client_ip, []).append(time.time())
                        st.session_state["reset_email_confirmed"] = current_email
                        st.session_state["reset_step"] = "confirm"
                        st.rerun()

            if message:
                render_feedback(*message)

        _send_section()

        if st.button("← Voltar ao login", key="btn_link_voltar", use_container_width=True):
            _switch_view("login")

        render_form_footer()


def _render_forgot_password_confirm(client_ip: str) -> None:
    email = st.session_state.get("reset_email_confirmed", "")
    _code_locked_out = events_in_window(_code_attempt_history, client_ip, _CODE_LOCKOUT_SECONDS) >= _MAX_CODE_ATTEMPTS
    with st.container(key="form-card"):
        _brand_header("Recuperar Acesso")
        if email:
            render_feedback("success", f"Enviamos um código para {email}. Confira também a pasta de spam.")
        else:
            st.markdown('<p class="form-subtitle">Digite o código recebido</p>', unsafe_allow_html=True)

        with st.container(key="password-fields-row"):
            fields_col, requirements_col = st.columns(2, gap="medium")
            with fields_col:
                code = st.text_input(
                    "Código de confirmação", placeholder="Digite o código recebido por e-mail", key="reset_code"
                )
                password = st.text_input(
                    "Nova senha", placeholder="Digite sua nova senha", type="password", key="reset_password"
                )
                confirm_password = st.text_input(
                    "Confirmar nova senha", placeholder="Digite sua nova senha novamente", type="password",
                    key="reset_confirm_password",
                )
            with requirements_col:
                st.markdown(
                    '<p class="password-requirements-title">Requisitos da senha</p>',
                    unsafe_allow_html=True,
                )
                render_password_requirements()
        error_placeholder = st.empty()
        submit = st.button(
            "Redefinir senha →", use_container_width=True, key="btn_redefinir_senha", disabled=_code_locked_out,
        )
        load_password_requirements_gate_script(
            password_key="reset_password",
            confirm_key="reset_confirm_password",
            button_key="btn_redefinir_senha",
            locked_out=_code_locked_out,
        )

        if _code_locked_out:
            _seconds = seconds_until_available(_code_attempt_history, client_ip, _CODE_LOCKOUT_SECONDS)
            with error_placeholder:
                render_feedback(
                    "warning",
                    "Muitas tentativas de código incorreto. Tente novamente em",
                    extra_html=' <span class="time-countdown" id="countdown"></span>.',
                )
            load_countdown_script(_seconds)
        elif submit:
            error = _validate_reset(code, password, confirm_password)
            if error:
                with error_placeholder:
                    render_feedback("error", error)
            else:
                try:
                    infrastructure.confirm_password_reset(email, code, password)
                except ClientError as exc:
                    if exc.response["Error"]["Code"] == "CodeMismatchException":
                        _code_attempt_history.setdefault(client_ip, []).append(time.time())
                        if events_in_window(_code_attempt_history, client_ip, _CODE_LOCKOUT_SECONDS) >= _MAX_CODE_ATTEMPTS:
                            st.rerun()
                    with error_placeholder:
                        render_feedback("error", _reset_error_message(exc))
                else:
                    try:
                        infrastructure.record_password_update(email)
                    except ClientError:
                        # Mesmo racional de record_login (_render_login_form): falha ao
                        # gravar o timestamp não deve travar a confirmação da troca de
                        # senha — só loga, não propaga.
                        logging.exception("Erro ao gravar password_updated_at")
                    st.session_state.pop("reset_step", None)
                    st.session_state.pop("reset_email_confirmed", None)
                    _switch_view("password_reset_success")

        @st.fragment(run_every=1)
        def _resend_section() -> None:
            # Recalculado a cada tick do fragmento (1x/s) a partir do tempo real decorrido —
            # ver o comentário equivalente em _send_section (_render_forgot_password_request)
            # sobre por que isso substitui o antigo reenable_button_key/DOM hack.
            _resend_locked = (
                events_in_window(_reset_attempt_history, client_ip, _RESEND_LOCKOUT_SECONDS) >= _MAX_RESEND_ATTEMPTS
            )
            # Mensagem computada e renderizada uma única vez, sem st.empty() — mesmo racional
            # de _send_section (_render_forgot_password_request): um placeholder recriado a
            # cada tick e preenchido logo em seguida pisca por ~200ms a cada segundo, porque o
            # Streamlit às vezes manda "limpa" e "preenche" em frames separados pro navegador.
            message: tuple[str, str] | None = None
            if _resend_locked:
                _seconds = seconds_until_available(_reset_attempt_history, client_ip, _RESEND_LOCKOUT_SECONDS)
                mm, ss = divmod(_seconds, 60)
                countdown = f"{mm:02d}:{ss:02d}"
                # .get() (não .pop()) — mesmo racional de _send_section: com run_every=1,
                # popar a flag no primeiro re-render a apagaria quase na hora, substituída
                # pelo aviso genérico no tick seguinte, antes do usuário conseguir ler.
                if st.session_state.get("code_just_resent", False):
                    message = (
                        "success",
                        "Novo código enviado. Confira a caixa de entrada e o spam. "
                        f"Aguarde {countdown} para pedir outro.",
                    )
                else:
                    message = ("warning", f"Aguarde {countdown} para pedir um novo código.")

            if message:
                render_feedback(*message)

            with st.container(key="resend-links-row"):
                link_col1, link_col2 = st.columns(2)
                with link_col1:
                    if st.button("← Voltar ao login", key="btn_link_voltar", use_container_width=True):
                        st.session_state.pop("reset_step", None)
                        st.session_state.pop("reset_email_confirmed", None)
                        _switch_view("login")
                with link_col2:
                    if st.button(
                        "Reenviar código", key="btn_reenviar_codigo", type="tertiary",
                        disabled=_resend_locked, use_container_width=True,
                    ):
                        try:
                            infrastructure.request_password_reset(email)
                        except ClientError:
                            # Mesmo racional anti-enumeration do passo 1 (request_password_reset acima).
                            pass
                        _reset_attempt_history.setdefault(client_ip, []).append(time.time())
                        st.session_state["code_just_resent"] = True
                        st.rerun(scope="fragment")

        _resend_section()

        render_form_footer()


def _validate_reset(code: str, password: str, confirm_password: str) -> str:
    if not code or not password or not confirm_password:
        return "Preencha todos os campos."
    if password != confirm_password:
        return "As senhas não coincidem."
    return validate_password(password)


def _reset_error_message(exc: ClientError) -> str:
    code = exc.response["Error"]["Code"]
    if code == "CodeMismatchException":
        return "Código incorreto."
    if code == "ExpiredCodeException":
        return "Código expirado. Volte e peça um novo."
    if code == "InvalidPasswordException":
        return "Senha não atende aos requisitos mínimos de segurança."
    return "Não foi possível redefinir a senha. Tente novamente."
