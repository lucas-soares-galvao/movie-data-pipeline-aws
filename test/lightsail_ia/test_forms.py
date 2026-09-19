from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from src import forms


def _client_error(code: str, operation: str = "Op", message: str | None = None) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message if message is not None else code}}, operation)


_VALID_PASSWORD = "Abcdef1!"


@pytest.fixture(autouse=True)
def _limpar_rate_limit_histories():
    forms._login_attempt_history.clear()
    forms._reset_attempt_history.clear()
    forms._code_attempt_history.clear()
    forms._signup_code_send_history.clear()
    forms._signup_code_attempt_history.clear()


def _patch_text_input(monkeypatch, values: dict):
    monkeypatch.setattr(
        forms.st, "text_input",
        lambda label, value="", placeholder=None, type=None, key=None, **k: values.get(key, value),
    )


def _patch_button(monkeypatch, clicked_keys: set):
    monkeypatch.setattr(forms.st, "button", lambda *a, key=None, **k: key in clicked_keys)


class _Rerun(Exception):
    """Sinaliza que st.rerun() foi chamado — em produção, st.rerun() aborta o script
    imediatamente (RerunException interna do Streamlit), então código depois dele nunca
    executa. Usar side_effect=_Rerun no mock reproduz esse corte quando importa (ex.:
    garantir que uma mensagem de erro não aparece depois de um rerun de lockout)."""


def _stub_common(monkeypatch, initial_state: dict | None = None, rerun_raises: bool = False) -> dict:
    session_state = dict(initial_state or {})
    monkeypatch.setattr(forms.st, "session_state", session_state)
    rerun = MagicMock(side_effect=_Rerun) if rerun_raises else MagicMock()
    monkeypatch.setattr(forms.st, "rerun", rerun)
    # st.fragment(run_every=1) depende de scheduling do ScriptRunContext real — em modo
    # bare ele simplesmente não chama a função decorada (nenhuma exceção, nenhum efeito).
    # As 3 funções de módulo abaixo (_render_signup_resend_section,
    # _render_forgot_password_resend_section, _render_forgot_password_send_section) são
    # decoradas uma única vez, na importação de forms.py — substituídas aqui pelo próprio
    # `.__wrapped__` (exposto pelo decorator do Streamlit), pulando o agendamento real de
    # fragment que não executa em modo bare.
    for nome in (
        "_render_signup_resend_section",
        "_render_forgot_password_resend_section",
        "_render_forgot_password_send_section",
    ):
        monkeypatch.setattr(forms, nome, getattr(forms, nome).__wrapped__)
    mocks = {"session_state": session_state, "rerun": rerun}
    for name in (
        "render_feedback", "load_form_button_toggle_script", "load_countdown_script",
        "render_form_footer", "load_password_requirements_gate_script",
        "render_password_requirements", "render_email_hint",
    ):
        m = MagicMock()
        monkeypatch.setattr(forms, name, m)
        mocks[name] = m
    return mocks


class TestSwitchView:
    def test_grava_view_e_chama_rerun(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(forms.st, "session_state", session_state)
        rerun = MagicMock()
        monkeypatch.setattr(forms.st, "rerun", rerun)

        forms._switch_view("signup")

        assert session_state["auth_view"] == "signup"
        rerun.assert_called_once()


class TestBrandHeader:
    def test_com_titulo_renderiza_page_title(self, monkeypatch):
        calls = []
        monkeypatch.setattr(forms.st, "markdown", lambda content, **k: calls.append(content))

        forms._brand_header("Minha Tela")

        assert any('class="form-page-title"' in c and "Minha Tela" in c for c in calls)

    def test_sem_titulo_nao_renderiza_page_title(self, monkeypatch):
        calls = []
        monkeypatch.setattr(forms.st, "markdown", lambda content, **k: calls.append(content))

        forms._brand_header()

        assert not any("form-page-title" in c for c in calls)


class TestValidateSignup:
    def test_campo_vazio(self):
        assert forms._validate_signup("", "a@x.com", _VALID_PASSWORD, _VALID_PASSWORD) == forms._ERRO_CAMPOS_EM_BRANCO

    def test_email_invalido(self):
        assert forms._validate_signup("Ana", "invalido", _VALID_PASSWORD, _VALID_PASSWORD) == forms._ERRO_EMAIL_INVALIDO

    def test_senhas_diferentes(self):
        assert forms._validate_signup("Ana", "a@x.com", _VALID_PASSWORD, "Outra2!") == forms._ERRO_SENHAS_NAO_COINCIDEM

    def test_senha_fraca_delega_para_validate_password(self):
        erro = forms._validate_signup("Ana", "a@x.com", "fraca", "fraca")
        assert "8 caracteres" in erro

    def test_tudo_valido_retorna_string_vazia(self):
        assert forms._validate_signup("Ana", "a@x.com", _VALID_PASSWORD, _VALID_PASSWORD) == ""


class TestSignupErrorMessage:
    def test_username_exists(self):
        assert forms._signup_error_message(_client_error("UsernameExistsException")) == "Esse e-mail já está cadastrado."

    def test_invalid_password(self):
        msg = forms._signup_error_message(_client_error("InvalidPasswordException"))
        assert "requisitos mínimos" in msg

    def test_codigo_desconhecido_usa_mensagem_generica(self):
        assert forms._signup_error_message(_client_error("QualquerOutraCoisa")) == "Não foi possível concluir o cadastro. Tente novamente."


class TestValidateSignupResumeDetails:
    def test_campo_vazio(self):
        assert forms._validate_signup_resume_details("", _VALID_PASSWORD, _VALID_PASSWORD) == forms._ERRO_CAMPOS_EM_BRANCO

    def test_senhas_diferentes(self):
        assert forms._validate_signup_resume_details("Ana", _VALID_PASSWORD, "Outra2!") == forms._ERRO_SENHAS_NAO_COINCIDEM

    def test_tudo_valido(self):
        assert forms._validate_signup_resume_details("Ana", _VALID_PASSWORD, _VALID_PASSWORD) == ""


class TestSignupCodeErrorMessage:
    def test_code_mismatch(self):
        assert forms._signup_code_error_message(_client_error("CodeMismatchException")) == "Código incorreto."

    def test_expired_code(self):
        assert "expirado" in forms._signup_code_error_message(_client_error("ExpiredCodeException"))

    @pytest.mark.parametrize("codigo", ["LimitExceededException", "TooManyFailedAttemptsException"])
    def test_limite_excedido(self, codigo):
        assert "alguns minutos" in forms._signup_code_error_message(_client_error(codigo))

    def test_alias_exists(self):
        assert "outra conta" in forms._signup_code_error_message(_client_error("AliasExistsException"))

    def test_user_not_found(self):
        assert forms._signup_code_error_message(_client_error("UserNotFoundException")) == "Cadastro não encontrado. Refaça o cadastro."

    def test_codigo_desconhecido(self):
        assert forms._signup_code_error_message(_client_error("Outro")) == "Não foi possível confirmar seu e-mail. Tente novamente."


class TestValidateReset:
    def test_campo_vazio(self):
        assert forms._validate_reset("", _VALID_PASSWORD, _VALID_PASSWORD) == forms._ERRO_CAMPOS_EM_BRANCO

    def test_senhas_diferentes(self):
        assert forms._validate_reset("123456", _VALID_PASSWORD, "Outra2!") == forms._ERRO_SENHAS_NAO_COINCIDEM

    def test_tudo_valido(self):
        assert forms._validate_reset("123456", _VALID_PASSWORD, _VALID_PASSWORD) == ""


class TestResetErrorMessage:
    def test_code_mismatch(self):
        assert forms._reset_error_message(_client_error("CodeMismatchException")) == "Código incorreto."

    def test_expired_code(self):
        assert "novo" in forms._reset_error_message(_client_error("ExpiredCodeException"))

    def test_invalid_password(self):
        assert "requisitos mínimos" in forms._reset_error_message(_client_error("InvalidPasswordException"))

    def test_codigo_desconhecido(self):
        assert forms._reset_error_message(_client_error("Outro")) == "Não foi possível redefinir a senha. Tente novamente."


class TestStartSignupResume:
    def test_email_nao_pendente_retorna_not_pending_sem_reenviar(self, monkeypatch):
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: "CONFIRMED")
        resend = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "resend_confirmation_code", resend)

        assert forms._start_signup_resume("a@x.com", "1.2.3.4") == "not_pending"
        resend.assert_not_called()

    def test_pendente_reenvia_codigo_e_retorna_ok(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(forms.st, "session_state", session_state)
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: "UNCONFIRMED")
        resend = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "resend_confirmation_code", resend)
        monkeypatch.setattr(forms.infrastructure, "get_unconfirmed_signup_name", lambda email: "Ana")

        result = forms._start_signup_resume("a@x.com", "1.2.3.4")

        assert result == "ok"
        resend.assert_called_once_with("a@x.com")
        assert session_state["signup_email_confirmed"] == "a@x.com"
        assert session_state["signup_name_confirmed"] == "Ana"
        assert session_state["signup_resumed"] is True

    def test_dentro_do_cooldown_nao_reenvia_mas_ainda_retorna_ok(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._signup_code_send_history[client_ip] = [forms.time.time()]
        monkeypatch.setattr(forms.st, "session_state", {})
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: "UNCONFIRMED")
        resend = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "resend_confirmation_code", resend)
        monkeypatch.setattr(forms.infrastructure, "get_unconfirmed_signup_name", lambda email: "Ana")

        result = forms._start_signup_resume("a@x.com", client_ip)

        assert result == "ok"
        resend.assert_not_called()

    def test_falha_ao_reenviar_retorna_resend_failed(self, monkeypatch):
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: "UNCONFIRMED")

        def _raise(email):
            raise _client_error("LimitExceededException")

        monkeypatch.setattr(forms.infrastructure, "resend_confirmation_code", _raise)

        assert forms._start_signup_resume("a@x.com", "1.2.3.4") == "resend_failed"

    def test_erro_ao_buscar_nome_usa_string_vazia_mas_ainda_retorna_ok(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(forms.st, "session_state", session_state)
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: "UNCONFIRMED")
        monkeypatch.setattr(forms.infrastructure, "resend_confirmation_code", lambda email: None)

        def _raise(email):
            raise IndexError

        monkeypatch.setattr(forms.infrastructure, "get_unconfirmed_signup_name", _raise)

        result = forms._start_signup_resume("a@x.com", "1.2.3.4")

        assert result == "ok"
        assert session_state["signup_name_confirmed"] == ""


class TestRenderForms:
    def test_ja_autenticado_retorna_sem_renderizar_nada(self, monkeypatch):
        monkeypatch.setattr(forms.st, "session_state", {"authenticated": True})
        load_css = MagicMock()
        monkeypatch.setattr(forms, "load_forms_css", load_css)
        stop = MagicMock()
        monkeypatch.setattr(forms.st, "stop", stop)

        forms.render_forms("1.2.3.4")

        load_css.assert_not_called()
        stop.assert_not_called()

    def _assert_dispatch(self, monkeypatch, view, expected_func_name):
        monkeypatch.setattr(forms.st, "session_state", {"auth_view": view})
        monkeypatch.setattr(forms, "load_forms_css", MagicMock())
        monkeypatch.setattr(forms.st, "stop", MagicMock())
        alvo = MagicMock()
        monkeypatch.setattr(forms, expected_func_name, alvo)

        forms.render_forms("1.2.3.4")

        alvo.assert_called_once()

    def test_view_signup_chama_render_signup(self, monkeypatch):
        self._assert_dispatch(monkeypatch, "signup", "_render_signup")

    def test_view_signup_resume_chama_render_signup_resume_request(self, monkeypatch):
        self._assert_dispatch(monkeypatch, "signup_resume", "_render_signup_resume_request")

    def test_view_signup_confirm_chama_render_signup_confirm(self, monkeypatch):
        self._assert_dispatch(monkeypatch, "signup_confirm", "_render_signup_confirm")

    def test_view_signup_success_chama_render_signup_success(self, monkeypatch):
        self._assert_dispatch(monkeypatch, "signup_success", "_render_signup_success")

    def test_view_forgot_password_chama_render_forgot_password(self, monkeypatch):
        self._assert_dispatch(monkeypatch, "forgot_password", "_render_forgot_password")

    def test_view_password_reset_success_chama_render_password_reset_success(self, monkeypatch):
        self._assert_dispatch(monkeypatch, "password_reset_success", "_render_password_reset_success")

    def test_view_default_chama_render_login_form(self, monkeypatch):
        monkeypatch.setattr(forms.st, "session_state", {})
        monkeypatch.setattr(forms, "load_forms_css", MagicMock())
        monkeypatch.setattr(forms.st, "stop", MagicMock())
        alvo = MagicMock()
        monkeypatch.setattr(forms, "_render_login_form", alvo)

        forms.render_forms("1.2.3.4")

        alvo.assert_called_once()

    def test_chama_stop_ao_final(self, monkeypatch):
        monkeypatch.setattr(forms.st, "session_state", {})
        monkeypatch.setattr(forms, "load_forms_css", MagicMock())
        monkeypatch.setattr(forms, "_render_login_form", MagicMock())
        stop = MagicMock()
        monkeypatch.setattr(forms.st, "stop", stop)

        forms.render_forms("1.2.3.4")

        stop.assert_called_once()


class TestRenderLoginForm:
    def test_bloqueado_mostra_aviso_sem_chamar_authenticate(self, monkeypatch):
        client_ip = "1.2.3.4"
        agora = forms.time.time()
        forms._login_attempt_history[client_ip] = [agora, agora, agora]
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, set())
        authenticate = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "authenticate", authenticate)

        forms._render_login_form(client_ip)

        authenticate.assert_not_called()
        mocks["render_feedback"].assert_called_once()
        assert mocks["render_feedback"].call_args.args[0] == "warning"
        mocks["load_countdown_script"].assert_called_once()

    def test_login_bem_sucedido_grava_sessao_e_chama_rerun(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"login_email": "ana@x.com", "login_password": _VALID_PASSWORD})
        _patch_button(monkeypatch, {"btn_entrar"})
        monkeypatch.setattr(forms.infrastructure, "authenticate", lambda email, password: "ok")
        monkeypatch.setattr(forms.infrastructure, "is_admin", lambda email: True)
        monkeypatch.setattr(forms.infrastructure, "get_user_profile", lambda email: {"name": "Ana"})
        record_login = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "record_login", record_login)

        forms._render_login_form("1.2.3.4")

        session_state = mocks["session_state"]
        assert session_state["authenticated"] is True
        assert session_state["user_email"] == "ana@x.com"
        assert session_state["is_admin"] is True
        assert session_state["user_name"] == "Ana"
        record_login.assert_called_once_with("ana@x.com")
        mocks["rerun"].assert_called_once()

    def test_login_bem_sucedido_com_falha_ao_buscar_nome_usa_string_vazia(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"login_email": "ana@x.com", "login_password": _VALID_PASSWORD})
        _patch_button(monkeypatch, {"btn_entrar"})
        monkeypatch.setattr(forms.infrastructure, "authenticate", lambda email, password: "ok")
        monkeypatch.setattr(forms.infrastructure, "is_admin", lambda email: False)

        def _raise(email):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(forms.infrastructure, "get_user_profile", _raise)
        monkeypatch.setattr(forms.infrastructure, "record_login", MagicMock())

        forms._render_login_form("1.2.3.4")

        assert mocks["session_state"]["user_name"] == ""

    def test_login_bem_sucedido_com_falha_ao_gravar_last_login_nao_propaga(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"login_email": "ana@x.com", "login_password": _VALID_PASSWORD})
        _patch_button(monkeypatch, {"btn_entrar"})
        monkeypatch.setattr(forms.infrastructure, "authenticate", lambda email, password: "ok")
        monkeypatch.setattr(forms.infrastructure, "is_admin", lambda email: False)
        monkeypatch.setattr(forms.infrastructure, "get_user_profile", lambda email: {"name": "Ana"})

        def _raise(email):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(forms.infrastructure, "record_login", _raise)

        forms._render_login_form("1.2.3.4")

        mocks["rerun"].assert_called_once()

    def test_login_pending_mostra_aviso_sem_rerun(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"login_email": "ana@x.com", "login_password": _VALID_PASSWORD})
        _patch_button(monkeypatch, {"btn_entrar"})
        monkeypatch.setattr(forms.infrastructure, "authenticate", lambda email, password: "pending")

        forms._render_login_form("1.2.3.4")

        mocks["rerun"].assert_not_called()
        mocks["render_feedback"].assert_called_once()
        assert mocks["render_feedback"].call_args.args[0] == "warning"

    def test_credenciais_invalidas_registra_falha_e_mostra_erro(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"login_email": "ana@x.com", "login_password": "Errada1!"})
        _patch_button(monkeypatch, {"btn_entrar"})
        monkeypatch.setattr(forms.infrastructure, "authenticate", lambda email, password: "invalid")

        forms._render_login_form(client_ip)

        mocks["rerun"].assert_not_called()
        mocks["render_feedback"].assert_called_once_with("error", "E-mail ou senha incorretos.")
        assert len(forms._login_attempt_history[client_ip]) == 1

    def test_terceira_credencial_invalida_chama_rerun_sem_mostrar_erro(self, monkeypatch):
        client_ip = "1.2.3.4"
        agora = forms.time.time()
        forms._login_attempt_history[client_ip] = [agora, agora]
        mocks = _stub_common(monkeypatch, rerun_raises=True)
        _patch_text_input(monkeypatch, {"login_email": "ana@x.com", "login_password": "Errada1!"})
        _patch_button(monkeypatch, {"btn_entrar"})
        monkeypatch.setattr(forms.infrastructure, "authenticate", lambda email, password: "invalid")

        with pytest.raises(_Rerun):
            forms._render_login_form(client_ip)

        mocks["rerun"].assert_called_once()
        mocks["render_feedback"].assert_not_called()

    def test_submit_sem_preencher_campos_mostra_erro(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"login_email": "", "login_password": ""})
        _patch_button(monkeypatch, {"btn_entrar"})
        authenticate = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "authenticate", authenticate)

        forms._render_login_form("1.2.3.4")

        authenticate.assert_not_called()
        mocks["render_feedback"].assert_called_once_with("error", "Preencha e-mail e senha.")

    def test_link_esqueci_a_senha_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, {"btn_link_esqueci"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_login_form("1.2.3.4")

        switch.assert_called_once_with("forgot_password")

    def test_link_novo_cadastro_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, {"btn_link_cadastro"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_login_form("1.2.3.4")

        switch.assert_called_once_with("signup")


class TestRenderPasswordResetSuccess:
    def test_botao_ir_para_login_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        _patch_button(monkeypatch, {"btn_ir_login_reset"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_password_reset_success()

        switch.assert_called_once_with("login")

    def test_sem_clique_nao_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        _patch_button(monkeypatch, set())
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_password_reset_success()

        switch.assert_not_called()


class TestRenderSignup:
    def _patch_fields(self, monkeypatch, **overrides):
        valores = {
            "signup_name": "Ana", "signup_email": "ana@x.com",
            "signup_password": _VALID_PASSWORD, "signup_confirm_password": _VALID_PASSWORD,
        }
        valores.update(overrides)
        _patch_text_input(monkeypatch, valores)

    def test_cadastro_valido_chama_sign_up_e_agenda_cooldown_de_reenvio(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        self._patch_fields(monkeypatch)
        _patch_button(monkeypatch, {"btn_cadastrar"})
        sign_up = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "sign_up", sign_up)
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup("1.2.3.4")

        sign_up.assert_called_once_with("ana@x.com", _VALID_PASSWORD, "Ana")
        assert mocks["session_state"]["signup_email_confirmed"] == "ana@x.com"
        assert mocks["session_state"]["signup_name_confirmed"] == "Ana"
        assert len(forms._signup_code_send_history["1.2.3.4"]) == 1
        switch.assert_called_once_with("signup_confirm")

    def test_validacao_local_falha_nao_chama_sign_up(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        self._patch_fields(monkeypatch, signup_confirm_password="Outra2!")
        _patch_button(monkeypatch, {"btn_cadastrar"})
        sign_up = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "sign_up", sign_up)

        forms._render_signup("1.2.3.4")

        sign_up.assert_not_called()
        mocks["render_feedback"].assert_called_once_with("error", forms._ERRO_SENHAS_NAO_COINCIDEM)

    def test_email_ja_existente_com_retomada_bem_sucedida_vai_para_confirmacao(self, monkeypatch):
        _stub_common(monkeypatch)
        self._patch_fields(monkeypatch)
        _patch_button(monkeypatch, {"btn_cadastrar"})

        def _raise(email, password, name):
            raise _client_error("UsernameExistsException")

        monkeypatch.setattr(forms.infrastructure, "sign_up", _raise)
        monkeypatch.setattr(forms, "_start_signup_resume", lambda email, client_ip: "ok")
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup("1.2.3.4")

        switch.assert_called_once_with("signup_confirm")

    def test_email_ja_existente_sem_retomada_mostra_erro(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        self._patch_fields(monkeypatch)
        _patch_button(monkeypatch, {"btn_cadastrar"})

        def _raise(email, password, name):
            raise _client_error("UsernameExistsException")

        monkeypatch.setattr(forms.infrastructure, "sign_up", _raise)
        monkeypatch.setattr(forms, "_start_signup_resume", lambda email, client_ip: "not_pending")
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup("1.2.3.4")

        switch.assert_not_called()
        mocks["render_feedback"].assert_called_once_with("error", "Esse e-mail já está cadastrado.")

    def test_erro_generico_do_cognito_mostra_mensagem_de_erro(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        self._patch_fields(monkeypatch)
        _patch_button(monkeypatch, {"btn_cadastrar"})

        def _raise(email, password, name):
            raise _client_error("InvalidParameterException")

        monkeypatch.setattr(forms.infrastructure, "sign_up", _raise)

        forms._render_signup("1.2.3.4")

        mocks["render_feedback"].assert_called_once_with("error", "Não foi possível concluir o cadastro. Tente novamente.")

    def test_link_retomar_cadastro_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        self._patch_fields(monkeypatch)
        _patch_button(monkeypatch, {"btn_link_retomar"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup("1.2.3.4")

        switch.assert_called_once_with("signup_resume")

    def test_link_voltar_ao_login_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        self._patch_fields(monkeypatch)
        _patch_button(monkeypatch, {"btn_link_voltar"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup("1.2.3.4")

        switch.assert_called_once_with("login")


class TestRenderSignupResumeRequest:
    def test_email_invalido_mostra_erro_sem_chamar_start_signup_resume(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"resume_email": "invalido"})
        _patch_button(monkeypatch, {"btn_reenviar_cadastro"})
        start = MagicMock()
        monkeypatch.setattr(forms, "_start_signup_resume", start)

        forms._render_signup_resume_request("1.2.3.4")

        start.assert_not_called()
        mocks["render_feedback"].assert_called_once_with("error", forms._ERRO_EMAIL_INVALIDO)

    def test_retomada_ok_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"resume_email": "ana@x.com"})
        _patch_button(monkeypatch, {"btn_reenviar_cadastro"})
        monkeypatch.setattr(forms, "_start_signup_resume", lambda email, client_ip: "ok")
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup_resume_request("1.2.3.4")

        switch.assert_called_once_with("signup_confirm")

    def test_sem_cadastro_pendente_mostra_erro(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"resume_email": "ana@x.com"})
        _patch_button(monkeypatch, {"btn_reenviar_cadastro"})
        monkeypatch.setattr(forms, "_start_signup_resume", lambda email, client_ip: "not_pending")

        forms._render_signup_resume_request("1.2.3.4")

        assert "pendente de confirmação" in mocks["render_feedback"].call_args.args[1]

    def test_falha_ao_reenviar_mostra_erro(self, monkeypatch):
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"resume_email": "ana@x.com"})
        _patch_button(monkeypatch, {"btn_reenviar_cadastro"})
        monkeypatch.setattr(forms, "_start_signup_resume", lambda email, client_ip: "resend_failed")

        forms._render_signup_resume_request("1.2.3.4")

        assert "Tente novamente em instantes" in mocks["render_feedback"].call_args.args[1]

    def test_link_voltar_ao_login_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"resume_email": ""})
        _patch_button(monkeypatch, {"btn_link_voltar"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup_resume_request("1.2.3.4")

        switch.assert_called_once_with("login")


class TestRenderSignupConfirm:
    def _base_state(self, **overrides):
        state = {"signup_email_confirmed": "ana@x.com", "signup_name_confirmed": "Ana"}
        state.update(overrides)
        return state

    def test_retomada_na_etapa_details_delega_para_resume_details(self, monkeypatch):
        _stub_common(monkeypatch, self._base_state(signup_resumed=True, signup_resume_step="details"))
        details = MagicMock()
        monkeypatch.setattr(forms, "_render_signup_resume_details", details)

        forms._render_signup_confirm("1.2.3.4")

        details.assert_called_once_with("ana@x.com", "Ana")

    def test_bloqueado_mostra_aviso_sem_chamar_confirm_sign_up(self, monkeypatch):
        client_ip = "1.2.3.4"
        agora = forms.time.time()
        forms._signup_code_attempt_history[client_ip] = [agora, agora, agora]
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, set())
        confirm = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "confirm_sign_up", confirm)

        forms._render_signup_confirm(client_ip)

        confirm.assert_not_called()
        # call_args_list[0] é o aviso "Enviamos um código para ana@x.com" (sempre exibido
        # quando há e-mail em sessão); o bloqueio é a chamada seguinte.
        assert mocks["render_feedback"].call_args_list[-1].args[0] == "warning"

    def test_codigo_em_branco_mostra_erro(self, monkeypatch):
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": ""})
        _patch_button(monkeypatch, {"btn_confirmar_email"})
        confirm = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "confirm_sign_up", confirm)

        forms._render_signup_confirm("1.2.3.4")

        confirm.assert_not_called()
        assert mocks["render_feedback"].call_args_list[-1] == (("error", "Digite o código recebido por e-mail."), {})

    def test_confirmacao_bem_sucedida_nao_retomada_vai_para_tela_de_sucesso(self, monkeypatch):
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": "123456"})
        _patch_button(monkeypatch, {"btn_confirmar_email"})
        monkeypatch.setattr(forms.infrastructure, "confirm_sign_up", MagicMock())
        monkeypatch.setattr(forms.infrastructure, "notify_new_signup", MagicMock())
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup_confirm("1.2.3.4")

        switch.assert_called_once_with("signup_success")
        assert "signup_email_confirmed" not in mocks["session_state"]

    def test_confirmacao_bem_sucedida_retomada_avanca_para_etapa_details(self, monkeypatch):
        mocks = _stub_common(monkeypatch, self._base_state(signup_resumed=True))
        _patch_text_input(monkeypatch, {"signup_code": "123456"})
        _patch_button(monkeypatch, {"btn_confirmar_email"})
        monkeypatch.setattr(forms.infrastructure, "confirm_sign_up", MagicMock())
        monkeypatch.setattr(forms.infrastructure, "notify_new_signup", MagicMock())

        forms._render_signup_confirm("1.2.3.4")

        assert mocks["session_state"]["signup_resume_step"] == "details"
        mocks["rerun"].assert_called_once()

    def test_falha_ao_notificar_admin_nao_propaga(self, monkeypatch):
        _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": "123456"})
        _patch_button(monkeypatch, {"btn_confirmar_email"})
        monkeypatch.setattr(forms.infrastructure, "confirm_sign_up", MagicMock())

        def _raise(email, name):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(forms.infrastructure, "notify_new_signup", _raise)
        monkeypatch.setattr(forms, "_switch_view", MagicMock())

        forms._render_signup_confirm("1.2.3.4")  # não deve levantar

    def test_codigo_incorreto_registra_tentativa_e_mostra_erro(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": "000000"})
        _patch_button(monkeypatch, {"btn_confirmar_email"})

        def _raise(email, code):
            raise _client_error("CodeMismatchException")

        monkeypatch.setattr(forms.infrastructure, "confirm_sign_up", _raise)

        forms._render_signup_confirm(client_ip)

        assert len(forms._signup_code_attempt_history[client_ip]) == 1
        assert mocks["render_feedback"].call_args_list[-1] == (("error", "Código incorreto."), {})

    def test_terceiro_codigo_incorreto_chama_rerun_sem_mensagem_de_erro(self, monkeypatch):
        client_ip = "1.2.3.4"
        agora = forms.time.time()
        forms._signup_code_attempt_history[client_ip] = [agora, agora]
        mocks = _stub_common(monkeypatch, self._base_state(), rerun_raises=True)
        _patch_text_input(monkeypatch, {"signup_code": "000000"})
        _patch_button(monkeypatch, {"btn_confirmar_email"})

        def _raise(email, code):
            raise _client_error("CodeMismatchException")

        monkeypatch.setattr(forms.infrastructure, "confirm_sign_up", _raise)

        with pytest.raises(_Rerun):
            forms._render_signup_confirm(client_ip)

        mocks["rerun"].assert_called_once()

    def test_resend_section_sem_bloqueio_nao_mostra_mensagem(self, monkeypatch):
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": ""})
        _patch_button(monkeypatch, set())

        forms._render_signup_confirm("1.2.3.4")

        # Único call é o aviso "Enviamos um código para ana@x.com" (email em sessão);
        # sem histórico de reenvio, a resend section não adiciona nenhuma mensagem própria.
        mocks["render_feedback"].assert_called_once()
        assert mocks["render_feedback"].call_args.args[0] == "success"

    def test_resend_section_bloqueado_com_reenvio_recente_mostra_sucesso(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._signup_code_send_history[client_ip] = [forms.time.time()]
        mocks = _stub_common(monkeypatch, self._base_state(signup_code_just_resent=True))
        _patch_text_input(monkeypatch, {"signup_code": ""})
        _patch_button(monkeypatch, set())

        forms._render_signup_confirm(client_ip)

        assert mocks["render_feedback"].call_args_list[-1].args[0] == "success"

    def test_resend_section_bloqueado_com_falha_recente_mostra_erro(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._signup_code_send_history[client_ip] = [forms.time.time()]
        mocks = _stub_common(monkeypatch, self._base_state(signup_resend_failed=True))
        _patch_text_input(monkeypatch, {"signup_code": ""})
        _patch_button(monkeypatch, set())

        forms._render_signup_confirm(client_ip)

        assert mocks["render_feedback"].call_args_list[-1].args[0] == "error"

    def test_resend_section_bloqueado_sem_reenvio_nem_falha_recente_mostra_aviso_generico(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._signup_code_send_history[client_ip] = [forms.time.time()]
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": ""})
        _patch_button(monkeypatch, set())

        forms._render_signup_confirm(client_ip)

        assert mocks["render_feedback"].call_args_list[-1].args[0] == "warning"
        assert "Aguarde" in mocks["render_feedback"].call_args_list[-1].args[1]

    def test_clique_em_reenviar_codigo_com_sucesso(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": ""})
        _patch_button(monkeypatch, {"btn_reenviar_codigo"})
        resend = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "resend_confirmation_code", resend)

        forms._render_signup_confirm(client_ip)

        resend.assert_called_once_with("ana@x.com")
        assert mocks["session_state"]["signup_code_just_resent"] is True
        assert len(forms._signup_code_send_history[client_ip]) == 1

    def test_clique_em_reenviar_codigo_com_falha(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": ""})
        _patch_button(monkeypatch, {"btn_reenviar_codigo"})

        def _raise(email):
            raise _client_error("LimitExceededException")

        monkeypatch.setattr(forms.infrastructure, "resend_confirmation_code", _raise)

        forms._render_signup_confirm(client_ip)

        assert mocks["session_state"]["signup_resend_failed"] is True
        assert mocks["session_state"]["signup_code_just_resent"] is False

    def test_link_voltar_ao_login_dentro_do_resend_limpa_sessao_e_troca_view(self, monkeypatch):
        mocks = _stub_common(monkeypatch, self._base_state())
        _patch_text_input(monkeypatch, {"signup_code": ""})
        _patch_button(monkeypatch, {"btn_link_voltar"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup_confirm("1.2.3.4")

        switch.assert_called_once_with("login")
        assert "signup_email_confirmed" not in mocks["session_state"]

    def test_sem_email_confirmado_mostra_subtitulo_generico(self, monkeypatch):
        calls = []
        _stub_common(monkeypatch, {"signup_email_confirmed": "", "signup_name_confirmed": ""})
        monkeypatch.setattr(forms.st, "markdown", lambda content, **k: calls.append(content))
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, set())

        forms._render_signup_confirm("1.2.3.4")

        assert any("Digite o código recebido" in c for c in calls)


class TestRenderSignupResumeDetails:
    def test_dados_validos_aplica_e_vai_para_sucesso(self, monkeypatch):
        mocks = _stub_common(monkeypatch, {
            "signup_email_confirmed": "a@x.com", "signup_name_confirmed": "Ana",
            "signup_resumed": True, "signup_resume_step": "details",
        })
        _patch_text_input(monkeypatch, {
            "signup_resume_name": "Ana Nova",
            "signup_resume_password": _VALID_PASSWORD,
            "signup_resume_confirm_password": _VALID_PASSWORD,
        })
        _patch_button(monkeypatch, {"btn_concluir_retomada"})
        apply_resumed = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "apply_resumed_signup", apply_resumed)
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup_resume_details("a@x.com", "Ana")

        apply_resumed.assert_called_once_with("a@x.com", _VALID_PASSWORD, "Ana Nova")
        switch.assert_called_once_with("signup_success")
        assert "signup_resumed" not in mocks["session_state"]

    def test_falha_ao_aplicar_nao_propaga_mas_ainda_avanca(self, monkeypatch):
        _stub_common(monkeypatch, {})
        _patch_text_input(monkeypatch, {
            "signup_resume_name": "Ana",
            "signup_resume_password": _VALID_PASSWORD,
            "signup_resume_confirm_password": _VALID_PASSWORD,
        })
        _patch_button(monkeypatch, {"btn_concluir_retomada"})

        def _raise(email, password, name):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(forms.infrastructure, "apply_resumed_signup", _raise)
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup_resume_details("a@x.com", "Ana")

        switch.assert_called_once_with("signup_success")

    def test_validacao_local_falha_nao_aplica(self, monkeypatch):
        mocks = _stub_common(monkeypatch, {})
        _patch_text_input(monkeypatch, {
            "signup_resume_name": "", "signup_resume_password": _VALID_PASSWORD,
            "signup_resume_confirm_password": _VALID_PASSWORD,
        })
        _patch_button(monkeypatch, {"btn_concluir_retomada"})
        apply_resumed = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "apply_resumed_signup", apply_resumed)

        forms._render_signup_resume_details("a@x.com", "Ana")

        apply_resumed.assert_not_called()
        # call_args_list[0] é o banner fixo "E-mail confirmado!..."; o erro de validação
        # é a chamada seguinte.
        assert mocks["render_feedback"].call_args_list[-1] == (("error", forms._ERRO_CAMPOS_EM_BRANCO), {})

    def test_link_voltar_retorna_para_etapa_codigo(self, monkeypatch):
        mocks = _stub_common(monkeypatch, {})
        _patch_text_input(monkeypatch, {
            "signup_resume_name": "Ana", "signup_resume_password": "",
            "signup_resume_confirm_password": "",
        })
        _patch_button(monkeypatch, {"btn_link_voltar_codigo"})

        forms._render_signup_resume_details("a@x.com", "Ana")

        assert mocks["session_state"]["signup_resume_step"] == "code"
        mocks["rerun"].assert_called_once()

    def test_email_exibido_e_escapado(self, monkeypatch):
        calls = []
        _stub_common(monkeypatch, {})
        monkeypatch.setattr(forms.st, "markdown", lambda content, **k: calls.append(content))
        _patch_text_input(monkeypatch, {"signup_resume_name": "Ana"})
        _patch_button(monkeypatch, set())

        forms._render_signup_resume_details('<script>a@x.com</script>', "Ana")

        assert any("&lt;script&gt;" in c for c in calls)


class TestRenderSignupSuccess:
    def test_botao_ir_para_login_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        _patch_button(monkeypatch, {"btn_ir_login_sucesso"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_signup_success()

        switch.assert_called_once_with("login")


class TestRenderForgotPassword:
    def test_step_padrao_chama_request(self, monkeypatch):
        monkeypatch.setattr(forms.st, "session_state", {})
        request = MagicMock()
        monkeypatch.setattr(forms, "_render_forgot_password_request", request)
        monkeypatch.setattr(forms, "_render_forgot_password_confirm", MagicMock())

        forms._render_forgot_password("1.2.3.4")

        request.assert_called_once_with("1.2.3.4")

    def test_step_confirm_chama_confirm(self, monkeypatch):
        monkeypatch.setattr(forms.st, "session_state", {"reset_step": "confirm"})
        confirm = MagicMock()
        monkeypatch.setattr(forms, "_render_forgot_password_confirm", confirm)
        monkeypatch.setattr(forms, "_render_forgot_password_request", MagicMock())

        forms._render_forgot_password("1.2.3.4")

        confirm.assert_called_once_with("1.2.3.4")


class TestRenderForgotPasswordRequest:
    def test_link_voltar_ao_login_troca_view(self, monkeypatch):
        _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"reset_email": ""})
        _patch_button(monkeypatch, {"btn_link_voltar"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_forgot_password_request("1.2.3.4")

        switch.assert_called_once_with("login")

    def test_bloqueado_mostra_aviso_generico(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._reset_attempt_history[client_ip] = [forms.time.time()]
        mocks = _stub_common(monkeypatch)
        _patch_text_input(monkeypatch, {"reset_email": ""})
        _patch_button(monkeypatch, set())

        forms._render_forgot_password_request(client_ip)

        assert mocks["render_feedback"].call_args.args[0] == "warning"

    def test_bloqueado_com_email_nao_registrado_mostra_mensagem_especifica(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._reset_attempt_history[client_ip] = [forms.time.time()]
        mocks = _stub_common(monkeypatch, {"email_not_registered": True})
        _patch_text_input(monkeypatch, {"reset_email": ""})
        _patch_button(monkeypatch, set())

        forms._render_forgot_password_request(client_ip)

        assert "ainda não tem cadastro" in mocks["render_feedback"].call_args.args[1]

    def test_bloqueado_com_cadastro_pendente_mostra_mensagem_especifica(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._reset_attempt_history[client_ip] = [forms.time.time()]
        mocks = _stub_common(monkeypatch, {"email_pending_approval": True})
        _patch_text_input(monkeypatch, {"reset_email": ""})
        _patch_button(monkeypatch, set())

        forms._render_forgot_password_request(client_ip)

        assert "aguardando aprovação" in mocks["render_feedback"].call_args.args[1]

    def test_email_invalido_mostra_erro(self, monkeypatch):
        mocks = _stub_common(monkeypatch, {"reset_email": "invalido"})
        _patch_text_input(monkeypatch, {"reset_email": "invalido"})
        _patch_button(monkeypatch, {"btn_enviar_codigo"})

        forms._render_forgot_password_request("1.2.3.4")

        assert mocks["render_feedback"].call_args == ((forms._ERRO_EMAIL_INVALIDO,), {}) or mocks["render_feedback"].call_args.args == ("error", forms._ERRO_EMAIL_INVALIDO)

    def test_email_sem_cadastro_marca_flag_e_faz_rerun_de_fragmento(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch, {"reset_email": "a@x.com"})
        _patch_text_input(monkeypatch, {"reset_email": "a@x.com"})
        _patch_button(monkeypatch, {"btn_enviar_codigo"})
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: None)
        request_reset = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "request_password_reset", request_reset)

        forms._render_forgot_password_request(client_ip)

        assert mocks["session_state"]["email_not_registered"] is True
        assert mocks["session_state"]["email_pending_approval"] is False
        request_reset.assert_not_called()
        mocks["rerun"].assert_called_once()

    def test_email_pendente_de_aprovacao_marca_flag_e_faz_rerun_de_fragmento(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch, {"reset_email": "a@x.com"})
        _patch_text_input(monkeypatch, {"reset_email": "a@x.com"})
        _patch_button(monkeypatch, {"btn_enviar_codigo"})
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: "UNCONFIRMED")
        request_reset = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "request_password_reset", request_reset)

        forms._render_forgot_password_request(client_ip)

        assert mocks["session_state"]["email_pending_approval"] is True
        request_reset.assert_not_called()

    def test_email_confirmado_solicita_reset_e_avanca_para_confirmacao(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch, {"reset_email": "a@x.com"})
        _patch_text_input(monkeypatch, {"reset_email": "a@x.com"})
        _patch_button(monkeypatch, {"btn_enviar_codigo"})
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: "CONFIRMED")
        request_reset = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "request_password_reset", request_reset)

        forms._render_forgot_password_request(client_ip)

        request_reset.assert_called_once_with("a@x.com")
        assert mocks["session_state"]["reset_email_confirmed"] == "a@x.com"
        assert mocks["session_state"]["reset_step"] == "confirm"
        mocks["rerun"].assert_called_once()

    def test_falha_ao_solicitar_reset_nao_propaga(self, monkeypatch):
        client_ip = "1.2.3.4"
        _stub_common(monkeypatch, {"reset_email": "a@x.com"})
        _patch_text_input(monkeypatch, {"reset_email": "a@x.com"})
        _patch_button(monkeypatch, {"btn_enviar_codigo"})
        monkeypatch.setattr(forms.infrastructure, "get_user_status", lambda email: "CONFIRMED")

        def _raise(email):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(forms.infrastructure, "request_password_reset", _raise)

        forms._render_forgot_password_request(client_ip)  # não deve levantar


class TestRenderForgotPasswordConfirm:
    def test_sem_email_em_sessao_mostra_subtitulo_generico(self, monkeypatch):
        calls = []
        _stub_common(monkeypatch, {"reset_email_confirmed": ""})
        monkeypatch.setattr(forms.st, "markdown", lambda content, **k: calls.append(content))
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, set())

        forms._render_forgot_password_confirm("1.2.3.4")

        assert any("Digite o código recebido" in c for c in calls)

    def test_bloqueado_mostra_aviso_sem_chamar_confirm(self, monkeypatch):
        client_ip = "1.2.3.4"
        agora = forms.time.time()
        forms._code_attempt_history[client_ip] = [agora, agora, agora]
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, set())
        confirm = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "confirm_password_reset", confirm)

        forms._render_forgot_password_confirm(client_ip)

        confirm.assert_not_called()
        assert mocks["render_feedback"].call_args_list[-1].args[0] == "warning"

    def test_validacao_local_falha_nao_chama_confirm(self, monkeypatch):
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {
            "reset_code": "", "reset_password": _VALID_PASSWORD, "reset_confirm_password": _VALID_PASSWORD,
        })
        _patch_button(monkeypatch, {"btn_redefinir_senha"})
        confirm = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "confirm_password_reset", confirm)

        forms._render_forgot_password_confirm("1.2.3.4")

        confirm.assert_not_called()
        assert mocks["render_feedback"].call_args_list[-1] == (("error", forms._ERRO_CAMPOS_EM_BRANCO), {})

    def test_confirmacao_bem_sucedida_grava_senha_e_avanca(self, monkeypatch):
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {
            "reset_code": "123456", "reset_password": _VALID_PASSWORD, "reset_confirm_password": _VALID_PASSWORD,
        })
        _patch_button(monkeypatch, {"btn_redefinir_senha"})
        monkeypatch.setattr(forms.infrastructure, "confirm_password_reset", MagicMock())
        record_update = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "record_password_update", record_update)
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_forgot_password_confirm("1.2.3.4")

        record_update.assert_called_once_with("a@x.com")
        switch.assert_called_once_with("password_reset_success")
        assert "reset_email_confirmed" not in mocks["session_state"]

    def test_falha_ao_gravar_password_updated_at_nao_impede_sucesso(self, monkeypatch):
        _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {
            "reset_code": "123456", "reset_password": _VALID_PASSWORD, "reset_confirm_password": _VALID_PASSWORD,
        })
        _patch_button(monkeypatch, {"btn_redefinir_senha"})
        monkeypatch.setattr(forms.infrastructure, "confirm_password_reset", MagicMock())

        def _raise(email):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(forms.infrastructure, "record_password_update", _raise)
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_forgot_password_confirm("1.2.3.4")

        switch.assert_called_once_with("password_reset_success")

    def test_codigo_incorreto_registra_tentativa_e_mostra_erro(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {
            "reset_code": "000000", "reset_password": _VALID_PASSWORD, "reset_confirm_password": _VALID_PASSWORD,
        })
        _patch_button(monkeypatch, {"btn_redefinir_senha"})

        def _raise(email, code, password):
            raise _client_error("CodeMismatchException")

        monkeypatch.setattr(forms.infrastructure, "confirm_password_reset", _raise)

        forms._render_forgot_password_confirm(client_ip)

        assert len(forms._code_attempt_history[client_ip]) == 1
        assert mocks["render_feedback"].call_args_list[-1] == (("error", "Código incorreto."), {})

    def test_terceiro_codigo_incorreto_chama_rerun_sem_mensagem_de_erro(self, monkeypatch):
        client_ip = "1.2.3.4"
        agora = forms.time.time()
        forms._code_attempt_history[client_ip] = [agora, agora]
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"}, rerun_raises=True)
        _patch_text_input(monkeypatch, {
            "reset_code": "000000", "reset_password": _VALID_PASSWORD, "reset_confirm_password": _VALID_PASSWORD,
        })
        _patch_button(monkeypatch, {"btn_redefinir_senha"})

        def _raise(email, code, password):
            raise _client_error("CodeMismatchException")

        monkeypatch.setattr(forms.infrastructure, "confirm_password_reset", _raise)

        with pytest.raises(_Rerun):
            forms._render_forgot_password_confirm(client_ip)

        mocks["rerun"].assert_called_once()

    def test_resend_section_bloqueado_com_reenvio_recente_mostra_sucesso(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._reset_attempt_history[client_ip] = [forms.time.time()]
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com", "code_just_resent": True})
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, set())

        forms._render_forgot_password_confirm(client_ip)

        assert mocks["render_feedback"].call_args_list[-1].args[0] == "success"

    def test_resend_section_bloqueado_sem_reenvio_recente_mostra_aviso_generico(self, monkeypatch):
        client_ip = "1.2.3.4"
        forms._reset_attempt_history[client_ip] = [forms.time.time()]
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, set())

        forms._render_forgot_password_confirm(client_ip)

        assert mocks["render_feedback"].call_args_list[-1].args[0] == "warning"

    def test_link_voltar_ao_login_dentro_do_resend_limpa_sessao(self, monkeypatch):
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, {"btn_link_voltar"})
        switch = MagicMock()
        monkeypatch.setattr(forms, "_switch_view", switch)

        forms._render_forgot_password_confirm("1.2.3.4")

        switch.assert_called_once_with("login")
        assert "reset_email_confirmed" not in mocks["session_state"]

    def test_clique_em_reenviar_codigo_agenda_novo_cooldown(self, monkeypatch):
        client_ip = "1.2.3.4"
        mocks = _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, {"btn_reenviar_codigo"})
        request_reset = MagicMock()
        monkeypatch.setattr(forms.infrastructure, "request_password_reset", request_reset)

        forms._render_forgot_password_confirm(client_ip)

        request_reset.assert_called_once_with("a@x.com")
        assert mocks["session_state"]["code_just_resent"] is True
        assert len(forms._reset_attempt_history[client_ip]) == 1

    def test_clique_em_reenviar_codigo_com_falha_nao_propaga(self, monkeypatch):
        client_ip = "1.2.3.4"
        _stub_common(monkeypatch, {"reset_email_confirmed": "a@x.com"})
        _patch_text_input(monkeypatch, {})
        _patch_button(monkeypatch, {"btn_reenviar_codigo"})

        def _raise(email):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(forms.infrastructure, "request_password_reset", _raise)

        forms._render_forgot_password_confirm(client_ip)  # não deve levantar
