from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from src import profile


def _client_error(code: str, operation: str = "Op", message: str | None = None) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message if message is not None else code}}, operation)


@pytest.fixture(autouse=True)
def _limpar_password_reauth_history():
    profile._password_reauth_history.clear()


class TestValidateNewPassword:
    def test_campo_vazio_retorna_mensagem_de_preencher_tudo(self):
        assert profile._validate_new_password("", "Abcdef1!", "Abcdef1!") == "Preencha todos os campos."
        assert profile._validate_new_password("Atual1!", "", "Abcdef1!") == "Preencha todos os campos."
        assert profile._validate_new_password("Atual1!", "Abcdef1!", "") == "Preencha todos os campos."

    def test_senhas_diferentes_retorna_mensagem_de_nao_coincidem(self):
        assert profile._validate_new_password("Atual1!", "Abcdef1!", "Outra2!") == "As senhas não coincidem."

    def test_senha_fraca_delega_para_validate_password(self):
        erro = profile._validate_new_password("Atual1!", "fraca", "fraca")
        assert "8 caracteres" in erro

    def test_senha_valida_retorna_string_vazia(self):
        assert profile._validate_new_password("Atual1!", "Abcdef1!", "Abcdef1!") == ""


class TestGetOwnProfile:
    def test_retorna_perfil_quando_busca_tem_sucesso(self, monkeypatch):
        monkeypatch.setattr(
            profile.infrastructure, "get_user_profile",
            lambda email: {"name": "Ana", "email": email},
        )
        assert profile.get_own_profile("ana@x.com") == {"name": "Ana", "email": "ana@x.com"}

    def test_retorna_fallback_quando_busca_falha(self, monkeypatch):
        def _raise(email):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(profile.infrastructure, "get_user_profile", _raise)

        assert profile.get_own_profile("ana@x.com") == {"name": "", "email": "ana@x.com"}


class TestRenderNavItem:
    def test_secao_inativa_sem_clique_nao_muda_estado_nem_chama_rerun(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {})
        monkeypatch.setattr(profile.st, "button", lambda *a, **k: False)
        rerun = MagicMock()
        monkeypatch.setattr(profile.st, "rerun", rerun)

        profile.render_nav_item("profile", "perfil", "user", "Perfil")

        assert profile.st.session_state == {}
        rerun.assert_not_called()

    def test_secao_inativa_com_clique_ativa_e_chama_rerun(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {})
        monkeypatch.setattr(profile.st, "button", lambda *a, **k: True)
        rerun = MagicMock()
        monkeypatch.setattr(profile.st, "rerun", rerun)

        profile.render_nav_item("profile", "senha", "lock", "Senha")

        assert profile.st.session_state["profile_active_section"] == "senha"
        rerun.assert_called_once()

    def test_secao_ja_ativa_com_clique_nao_chama_rerun(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {"profile_active_section": "perfil"})
        monkeypatch.setattr(profile.st, "button", lambda *a, **k: True)
        rerun = MagicMock()
        monkeypatch.setattr(profile.st, "rerun", rerun)

        profile.render_nav_item("profile", "perfil", "user", "Perfil")

        rerun.assert_not_called()


class TestRenderNavBar:
    def test_chama_render_nav_item_uma_vez_por_secao_com_o_scope_certo(self, monkeypatch):
        chamadas = []
        monkeypatch.setattr(
            profile, "render_nav_item",
            lambda scope, value, icon_name, label: chamadas.append((scope, value, icon_name, label)),
        )

        profile.render_nav_bar("profile", profile._PROFILE_SECTIONS)

        assert chamadas == [
            ("profile", "perfil", "user", "Perfil"),
            ("profile", "senha", "lock", "Senha"),
        ]


class TestRenderProfileTab:
    def test_nome_inalterado_nao_chama_update_user_name_nem_feedback(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {})
        monkeypatch.setattr(profile.st, "button", lambda *a, key=None, **k: key == "btn_salvar_perfil")
        update_user_name = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "update_user_name", update_user_name)
        feedback = MagicMock()
        monkeypatch.setattr(profile, "render_feedback", feedback)

        profile.render_profile_tab({"name": "Ana", "email": "ana@x.com"})

        update_user_name.assert_not_called()
        feedback.assert_not_called()

    def test_nome_em_branco_mostra_erro_sem_chamar_update_user_name(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {})
        monkeypatch.setattr(profile.st, "button", lambda *a, key=None, **k: key == "btn_salvar_perfil")
        update_user_name = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "update_user_name", update_user_name)
        feedback = MagicMock()
        monkeypatch.setattr(profile, "render_feedback", feedback)

        profile.render_profile_tab({"name": "", "email": "ana@x.com"})

        update_user_name.assert_not_called()
        feedback.assert_called_once_with("error", "O nome não pode ficar em branco.")

    def test_nome_alterado_chama_update_user_name_e_feedback_de_sucesso(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {})
        monkeypatch.setattr(
            profile.st, "text_input",
            lambda label, value="", key=None, **k: "Novo Nome" if key == "profile_name" else value,
        )
        monkeypatch.setattr(profile.st, "button", lambda *a, key=None, **k: key == "btn_salvar_perfil")
        update_user_name = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "update_user_name", update_user_name)
        feedback = MagicMock()
        monkeypatch.setattr(profile, "render_feedback", feedback)

        profile.render_profile_tab({"name": "Ana", "email": "ana@x.com"})

        update_user_name.assert_called_once_with("ana@x.com", "Novo Nome")
        assert profile.st.session_state["user_name"] == "Novo Nome"
        feedback.assert_called_once_with("success", "Perfil atualizado com sucesso.")

    def test_botao_nao_clicado_nao_chama_update_user_name_nem_feedback(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {})
        monkeypatch.setattr(profile.st, "button", lambda *a, **k: False)
        update_user_name = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "update_user_name", update_user_name)
        feedback = MagicMock()
        monkeypatch.setattr(profile, "render_feedback", feedback)

        profile.render_profile_tab({"name": "Ana", "email": "ana@x.com"})

        update_user_name.assert_not_called()
        feedback.assert_not_called()


def _patch_password_fields(monkeypatch, current="", new="", confirm=""):
    valores = {
        "profile_current_password": current,
        "profile_new_password": new,
        "profile_confirm_password": confirm,
    }
    monkeypatch.setattr(
        profile.st, "text_input",
        lambda label, type=None, key=None, **k: valores.get(key, ""),
    )


def _patch_submit(monkeypatch, clicado: bool):
    monkeypatch.setattr(profile.st, "button", lambda *a, key=None, **k: clicado if key == "btn_salvar_senha" else False)


def _patch_password_helpers(monkeypatch):
    gate = MagicMock()
    countdown = MagicMock()
    feedback = MagicMock()
    monkeypatch.setattr(profile, "load_password_requirements_gate_script", gate)
    monkeypatch.setattr(profile, "load_countdown_script", countdown)
    monkeypatch.setattr(profile, "render_feedback", feedback)
    monkeypatch.setattr(profile, "render_password_requirements", MagicMock())
    return gate, countdown, feedback


class TestRenderPasswordTab:
    def test_sem_bloqueio_e_sem_clique_nao_chama_change_password(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {})
        _patch_password_fields(monkeypatch)
        _patch_submit(monkeypatch, clicado=False)
        gate, countdown, feedback = _patch_password_helpers(monkeypatch)
        change_password = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "change_password", change_password)

        profile.render_password_tab("1.2.3.4")

        change_password.assert_not_called()
        feedback.assert_not_called()
        gate.assert_called_once()
        assert gate.call_args.kwargs["locked_out"] is False

    def test_bloqueado_por_tentativas_mostra_aviso_e_nao_chama_change_password(self, monkeypatch):
        client_ip = "1.2.3.4"
        agora = profile.time.time()
        profile._password_reauth_history[client_ip] = [agora, agora, agora]
        monkeypatch.setattr(profile.st, "session_state", {})
        _patch_password_fields(monkeypatch)
        _patch_submit(monkeypatch, clicado=True)
        gate, countdown, feedback = _patch_password_helpers(monkeypatch)
        change_password = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "change_password", change_password)

        profile.render_password_tab(client_ip)

        change_password.assert_not_called()
        feedback.assert_called_once()
        assert feedback.call_args.args[0] == "warning"
        countdown.assert_called_once()
        assert gate.call_args.kwargs["locked_out"] is True

    def test_validacao_local_falha_nao_chama_change_password(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {})
        _patch_password_fields(monkeypatch, current="Atual1!", new="Abcdef1!", confirm="Diferente2!")
        _patch_submit(monkeypatch, clicado=True)
        gate, countdown, feedback = _patch_password_helpers(monkeypatch)
        change_password = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "change_password", change_password)

        profile.render_password_tab("1.2.3.4")

        change_password.assert_not_called()
        feedback.assert_called_once_with("error", "As senhas não coincidem.")

    def test_senha_atual_incorreta_registra_tentativa_e_mostra_erro(self, monkeypatch):
        client_ip = "1.2.3.4"
        monkeypatch.setattr(profile.st, "session_state", {"user_email": "ana@x.com"})
        _patch_password_fields(monkeypatch, current="Errada1!", new="Abcdef1!", confirm="Abcdef1!")
        _patch_submit(monkeypatch, clicado=True)
        gate, countdown, feedback = _patch_password_helpers(monkeypatch)
        monkeypatch.setattr(profile.infrastructure, "change_password", lambda *a, **k: "invalid")
        record_password_update = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "record_password_update", record_password_update)

        profile.render_password_tab(client_ip)

        record_password_update.assert_not_called()
        feedback.assert_called_once_with("error", "Senha atual incorreta.")
        assert len(profile._password_reauth_history[client_ip]) == 1

    def test_senha_atualizada_com_sucesso_limpa_campos_e_mostra_sucesso(self, monkeypatch):
        session_state = {
            "user_email": "ana@x.com",
            "profile_current_password": "Atual1!",
            "profile_new_password": "Abcdef1!",
            "profile_confirm_password": "Abcdef1!",
        }
        monkeypatch.setattr(profile.st, "session_state", session_state)
        _patch_password_fields(monkeypatch, current="Atual1!", new="Abcdef1!", confirm="Abcdef1!")
        _patch_submit(monkeypatch, clicado=True)
        gate, countdown, feedback = _patch_password_helpers(monkeypatch)
        monkeypatch.setattr(profile.infrastructure, "change_password", lambda *a, **k: "ok")
        record_password_update = MagicMock()
        monkeypatch.setattr(profile.infrastructure, "record_password_update", record_password_update)

        profile.render_password_tab("1.2.3.4")

        record_password_update.assert_called_once_with("ana@x.com")
        feedback.assert_called_once_with("success", "Senha atualizada com sucesso.")
        assert "profile_current_password" not in session_state
        assert "profile_new_password" not in session_state
        assert "profile_confirm_password" not in session_state

    def test_falha_ao_gravar_password_updated_at_nao_impede_sucesso(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {"user_email": "ana@x.com"})
        _patch_password_fields(monkeypatch, current="Atual1!", new="Abcdef1!", confirm="Abcdef1!")
        _patch_submit(monkeypatch, clicado=True)
        gate, countdown, feedback = _patch_password_helpers(monkeypatch)
        monkeypatch.setattr(profile.infrastructure, "change_password", lambda *a, **k: "ok")

        def _raise(email):
            raise _client_error("InternalErrorException")

        monkeypatch.setattr(profile.infrastructure, "record_password_update", _raise)

        profile.render_password_tab("1.2.3.4")

        feedback.assert_called_once_with("success", "Senha atualizada com sucesso.")


class TestRenderProfilePanel:
    def test_secao_padrao_perfil_chama_render_profile_tab(self, monkeypatch):
        monkeypatch.setattr(profile.st, "session_state", {"user_email": "ana@x.com"})
        monkeypatch.setattr(profile, "load_profile_css", MagicMock())
        monkeypatch.setattr(profile, "get_own_profile", lambda email: {"name": "Ana", "email": email})
        monkeypatch.setattr(profile, "render_nav_bar", MagicMock())
        profile_tab = MagicMock()
        password_tab = MagicMock()
        monkeypatch.setattr(profile, "render_profile_tab", profile_tab)
        monkeypatch.setattr(profile, "render_password_tab", password_tab)

        profile.render_profile_panel("1.2.3.4")

        profile_tab.assert_called_once_with({"name": "Ana", "email": "ana@x.com"})
        password_tab.assert_not_called()

    def test_secao_senha_chama_render_password_tab(self, monkeypatch):
        monkeypatch.setattr(
            profile.st, "session_state",
            {"user_email": "ana@x.com", "profile_active_section": "senha"},
        )
        monkeypatch.setattr(profile, "load_profile_css", MagicMock())
        monkeypatch.setattr(profile, "get_own_profile", lambda email: {"name": "Ana", "email": email})
        monkeypatch.setattr(profile, "render_nav_bar", MagicMock())
        profile_tab = MagicMock()
        password_tab = MagicMock()
        monkeypatch.setattr(profile, "render_profile_tab", profile_tab)
        monkeypatch.setattr(profile, "render_password_tab", password_tab)

        profile.render_profile_panel("1.2.3.4")

        password_tab.assert_called_once_with("1.2.3.4")
        profile_tab.assert_not_called()
