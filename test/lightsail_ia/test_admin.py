from unittest.mock import MagicMock

from src import admin


class _FakeColumn:
    """Substitui uma coluna de st.columns() quando o teste só precisa de .button()."""

    def __init__(self, clicked: bool = False):
        self._clicked = clicked

    def button(self, *args, **kwargs):
        return self._clicked


class _FakeComponentResult:
    """Simula o objeto de retorno de st.components.v2.component(), que expõe os
    cliques via getattr dinâmico (ex.: getattr(result, "approve_ana@x.com"))."""

    def __init__(self, **attrs):
        for key, value in attrs.items():
            setattr(self, key, value)


def _patch_admin_table_component(monkeypatch, **result_attrs):
    fake_result = _FakeComponentResult(**result_attrs)
    monkeypatch.setattr(
        admin.st.components.v2, "component",
        lambda *a, **k: (lambda **on_changes: fake_result),
    )


class TestFormatDatetime:
    def test_valor_vazio_retorna_nunca(self):
        assert admin._format_datetime("") == "Nunca"

    def test_formata_timestamp_utc_para_horario_de_sao_paulo(self):
        assert admin._format_datetime("2024-01-15T12:00:00+00:00") == "15/01/2024 09:00"


class TestStatusLabel:
    def test_unconfirmed_retorna_inativo(self):
        assert admin._status_label({"kind": "unconfirmed", "enabled": True}) == "Inativo"

    def test_pending_retorna_novo(self):
        assert admin._status_label({"kind": "pending", "enabled": False}) == "Novo"

    def test_active_habilitado_retorna_ativo(self):
        assert admin._status_label({"kind": "active", "enabled": True}) == "Ativo"

    def test_active_desabilitado_retorna_revogado(self):
        assert admin._status_label({"kind": "active", "enabled": False}) == "Revogado"


class TestRevokeKind:
    def test_pending_retorna_reject(self):
        assert admin._revoke_kind({"kind": "pending"}) == "reject"

    def test_unconfirmed_retorna_remove_unconfirmed(self):
        assert admin._revoke_kind({"kind": "unconfirmed"}) == "remove_unconfirmed"

    def test_active_retorna_revoke(self):
        assert admin._revoke_kind({"kind": "active"}) == "revoke"


class TestRevokeVisible:
    def test_admin_nunca_e_revogavel(self):
        assert admin._revoke_visible({"kind": "active", "enabled": True, "is_admin": True}) is False

    def test_pendente_nao_admin_e_revogavel(self):
        assert admin._revoke_visible({"kind": "pending", "enabled": False, "is_admin": False}) is True

    def test_ativo_habilitado_nao_admin_e_revogavel(self):
        assert admin._revoke_visible({"kind": "active", "enabled": True, "is_admin": False}) is True

    def test_ativo_ja_desabilitado_nao_e_revogavel(self):
        assert admin._revoke_visible({"kind": "active", "enabled": False, "is_admin": False}) is False


class TestBuildRows:
    def test_combina_e_marca_origem_das_3_listas(self, monkeypatch):
        monkeypatch.setattr(admin.infrastructure, "list_pending_users", lambda: [{"email": "p@x.com", "name": "P"}])
        monkeypatch.setattr(admin.infrastructure, "list_active_users", lambda: [{"email": "a@x.com", "name": "A"}])
        monkeypatch.setattr(admin.infrastructure, "list_unconfirmed_users", lambda: [{"email": "u@x.com", "name": "U"}])
        monkeypatch.setattr(admin.infrastructure, "is_admin", lambda email: email == "a@x.com")
        monkeypatch.setattr(admin.infrastructure, "admin_table_sort_key", lambda row: row["email"])

        rows = admin._build_rows()

        by_email = {row["email"]: row for row in rows}
        assert by_email["p@x.com"]["kind"] == "pending"
        assert by_email["a@x.com"]["kind"] == "active"
        assert by_email["u@x.com"]["kind"] == "unconfirmed"
        assert by_email["a@x.com"]["is_admin"] is True
        assert by_email["p@x.com"]["is_admin"] is False

    def test_ordena_pelo_sort_key_de_infrastructure_em_ordem_reversa(self, monkeypatch):
        monkeypatch.setattr(admin.infrastructure, "list_pending_users", lambda: [])
        monkeypatch.setattr(
            admin.infrastructure, "list_active_users",
            lambda: [{"email": "b@x.com", "name": "B"}, {"email": "a@x.com", "name": "A"}],
        )
        monkeypatch.setattr(admin.infrastructure, "list_unconfirmed_users", lambda: [])
        monkeypatch.setattr(admin.infrastructure, "is_admin", lambda email: False)
        monkeypatch.setattr(admin.infrastructure, "admin_table_sort_key", lambda row: row["name"])

        rows = admin._build_rows()

        assert [row["name"] for row in rows] == ["B", "A"]


class TestBuildTableData:
    def test_monta_colunas_em_portugues_com_status_e_datas_formatadas(self):
        rows = [{
            "name": "Ana", "email": "ana@x.com",
            "created_at": "", "updated_at": "", "last_login": "",
            "is_admin": True, "kind": "active", "enabled": True,
        }]

        data = admin._build_table_data(rows)

        assert data == [{
            "Nome": "Ana", "E-mail": "ana@x.com",
            "Cadastrado em": "Nunca", "Atualizado em": "Nunca", "Último acesso": "Nunca",
            "Admin": "Sim", "Status": "Ativo",
        }]

    def test_nao_admin_gera_coluna_admin_nao(self):
        rows = [{
            "name": "Bea", "email": "bea@x.com",
            "created_at": "", "updated_at": "", "last_login": "",
            "is_admin": False, "kind": "pending", "enabled": False,
        }]

        data = admin._build_table_data(rows)

        assert data[0]["Admin"] == "Não"
        assert data[0]["Status"] == "Novo"


class TestBuildTableHtml:
    def test_colgroup_reflete_as_larguras_configuradas(self):
        html_out = admin._build_table_html([], [])
        for weight in admin._COLUMN_WEIGHTS:
            assert f'<col style="width:{weight}px">' in html_out

    def test_cabecalho_contem_todos_os_rotulos_de_coluna(self):
        html_out = admin._build_table_html([], [])
        for label in admin._COLUMN_LABELS:
            assert f">{label}<" in html_out

    def test_colunas_centralizadas_ganham_classe_col_center(self):
        html_out = admin._build_table_html([], [])
        header_cells = html_out.split("<thead>")[1].split("</thead>")[0]
        for i, label in enumerate(admin._COLUMN_LABELS):
            cell = f'>{label}<'
            if i in admin._CENTERED_COLUMNS:
                assert f'class="col-center">{label}' in header_cells
            else:
                assert cell in header_cells
                assert f'class="col-center">{label}' not in header_cells


class TestBuildTableRowHtml:
    def _row_e_entry(self, **overrides):
        row = {
            "email": "ana@x.com", "name": "Ana", "kind": "active",
            "enabled": True, "is_admin": False,
        }
        row.update(overrides)
        entry = {
            "Nome": row["name"], "E-mail": row["email"],
            "Cadastrado em": "Nunca", "Atualizado em": "Nunca", "Último acesso": "Nunca",
            "Admin": "Não", "Status": "Ativo",
        }
        return row, entry

    def test_linha_ativa_nao_admin_exibe_botao_de_revogar_sem_aprovar(self):
        row, entry = self._row_e_entry()
        row_html = admin._build_table_row_html(row, entry)
        assert "btn-approve" not in row_html
        assert 'class="btn-revoke" data-email="ana@x.com"' in row_html

    def test_linha_pendente_exibe_botao_de_aprovar_e_de_revogar(self):
        row, entry = self._row_e_entry(kind="pending")
        row_html = admin._build_table_row_html(row, entry)
        assert 'class="btn-approve" data-email="ana@x.com"' in row_html
        assert 'class="btn-revoke" data-email="ana@x.com"' in row_html

    def test_linha_admin_nunca_exibe_botao_de_revogar(self):
        row, entry = self._row_e_entry(is_admin=True)
        row_html = admin._build_table_row_html(row, entry)
        assert "btn-revoke" not in row_html

    def test_escapa_xss_no_email_e_no_nome(self):
        row, entry = self._row_e_entry(email='<script>x</script>', kind="pending")
        entry["Nome"] = '<b>Ana</b>'
        row_html = admin._build_table_row_html(row, entry)
        assert "<script>" not in row_html
        assert "&lt;script&gt;" in row_html
        assert "<b>Ana</b>" not in row_html


class TestReadStatic:
    def test_le_arquivo_estatico_real_de_admin_table(self):
        css = admin._read_static("css", "admin_table.css")
        assert ".admin-table-wrap" in css


class TestRenderTable:
    def test_sem_usuarios_exibe_mensagem_vazia(self, monkeypatch):
        monkeypatch.setattr(admin.st, "session_state", {})
        monkeypatch.setattr(admin, "_build_rows", lambda: [])
        markdown_calls = []
        monkeypatch.setattr(admin.st, "markdown", lambda content, **k: markdown_calls.append(content))
        render_users_table = MagicMock()
        monkeypatch.setattr(admin, "_render_users_table", render_users_table)

        admin._render_table()

        render_users_table.assert_not_called()
        assert any("Nenhum usuário encontrado." in c for c in markdown_calls)

    def test_com_usuarios_chama_render_users_table(self, monkeypatch):
        monkeypatch.setattr(admin.st, "session_state", {})
        rows = [{"email": "a@x.com"}]
        monkeypatch.setattr(admin, "_build_rows", lambda: rows)
        render_users_table = MagicMock()
        monkeypatch.setattr(admin, "_render_users_table", render_users_table)

        admin._render_table()

        render_users_table.assert_called_once_with(rows)

    def test_feedback_pendente_e_renderizado_e_removido_da_sessao(self, monkeypatch):
        session_state = {"admin_action_feedback": {"kind": "success", "text": "Ok."}}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        monkeypatch.setattr(admin, "_build_rows", lambda: [])
        monkeypatch.setattr(admin.st, "markdown", lambda *a, **k: None)
        feedback = MagicMock()
        monkeypatch.setattr(admin, "render_feedback", feedback)

        admin._render_table()

        feedback.assert_called_once_with("success", "Ok.")
        assert "admin_action_feedback" not in session_state

    def test_sem_feedback_pendente_nao_chama_render_feedback(self, monkeypatch):
        monkeypatch.setattr(admin.st, "session_state", {})
        monkeypatch.setattr(admin, "_build_rows", lambda: [])
        monkeypatch.setattr(admin.st, "markdown", lambda *a, **k: None)
        feedback = MagicMock()
        monkeypatch.setattr(admin, "render_feedback", feedback)

        admin._render_table()

        feedback.assert_not_called()


class TestQueuePendingAction:
    def test_grava_acao_pendente_e_chama_rerun(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        rerun = MagicMock()
        monkeypatch.setattr(admin.st, "rerun", rerun)

        admin._queue_pending_action("approve", {"email": "a@x.com", "name": "Ana"})

        assert session_state["admin_pending_action"] == {"kind": "approve", "email": "a@x.com", "name": "Ana"}
        rerun.assert_called_once()


class TestRenderUsersTable:
    _ROW_PENDING = {
        "email": "p@x.com", "name": "P", "kind": "pending", "enabled": False, "is_admin": False,
        "created_at": "", "updated_at": "", "last_login": "",
    }
    _ROW_ACTIVE = {
        "email": "a@x.com", "name": "A", "kind": "active", "enabled": True, "is_admin": False,
        "created_at": "", "updated_at": "", "last_login": "",
    }

    def _patch_static_reads(self, monkeypatch):
        monkeypatch.setattr(admin, "_read_static", lambda sub_dir, file_name: "")

    def test_sem_clique_nao_enfileira_nenhuma_acao(self, monkeypatch):
        self._patch_static_reads(monkeypatch)
        monkeypatch.setattr(admin.st, "session_state", {})
        _patch_admin_table_component(monkeypatch)
        queue = MagicMock()
        monkeypatch.setattr(admin, "_queue_pending_action", queue)

        admin._render_users_table([self._ROW_PENDING, self._ROW_ACTIVE])

        queue.assert_not_called()

    def test_clique_em_aprovar_enfileira_approve(self, monkeypatch):
        self._patch_static_reads(monkeypatch)
        monkeypatch.setattr(admin.st, "session_state", {})
        _patch_admin_table_component(monkeypatch, **{"approve_p@x.com": True})
        queue = MagicMock()
        monkeypatch.setattr(admin, "_queue_pending_action", queue)

        admin._render_users_table([self._ROW_PENDING])

        queue.assert_called_once_with("approve", self._ROW_PENDING)

    def test_clique_em_revogar_usuario_ativo_enfileira_revoke(self, monkeypatch):
        self._patch_static_reads(monkeypatch)
        monkeypatch.setattr(admin.st, "session_state", {})
        _patch_admin_table_component(monkeypatch, **{"revoke_a@x.com": True})
        queue = MagicMock()
        monkeypatch.setattr(admin, "_queue_pending_action", queue)

        admin._render_users_table([self._ROW_ACTIVE])

        queue.assert_called_once_with("revoke", self._ROW_ACTIVE)

    def test_clique_em_revogar_pendente_enfileira_reject(self, monkeypatch):
        self._patch_static_reads(monkeypatch)
        monkeypatch.setattr(admin.st, "session_state", {})
        _patch_admin_table_component(monkeypatch, **{"revoke_p@x.com": True})
        queue = MagicMock()
        monkeypatch.setattr(admin, "_queue_pending_action", queue)

        admin._render_users_table([self._ROW_PENDING])

        queue.assert_called_once_with("reject", self._ROW_PENDING)

    def test_acao_pendente_na_sessao_abre_dialogo_de_confirmacao(self, monkeypatch):
        self._patch_static_reads(monkeypatch)
        pending = {"kind": "approve", "email": "p@x.com", "name": "P"}
        monkeypatch.setattr(admin.st, "session_state", {"admin_pending_action": pending})
        _patch_admin_table_component(monkeypatch)
        dialog = MagicMock()
        monkeypatch.setattr(admin, "_render_confirm_dialog", dialog)

        admin._render_users_table([self._ROW_PENDING])

        dialog.assert_called_once_with(pending)

    def test_sem_acao_pendente_nao_abre_dialogo(self, monkeypatch):
        self._patch_static_reads(monkeypatch)
        monkeypatch.setattr(admin.st, "session_state", {})
        _patch_admin_table_component(monkeypatch)
        dialog = MagicMock()
        monkeypatch.setattr(admin, "_render_confirm_dialog", dialog)

        admin._render_users_table([self._ROW_PENDING])

        dialog.assert_not_called()


def _patch_confirm_dialog_widgets(monkeypatch, notify: bool, cancelled: bool = False, confirmed: bool = False):
    monkeypatch.setattr(admin.st, "write", lambda *a, **k: None)
    monkeypatch.setattr(admin.st, "checkbox", lambda *a, **k: notify)
    monkeypatch.setattr(
        admin.st, "columns",
        lambda *a, **k: (_FakeColumn(cancelled), _FakeColumn(confirmed)),
    )


class TestRenderConfirmDialog:
    def _run(self, pending: dict):
        admin._render_confirm_dialog.__wrapped__(pending)

    def test_aprovar_confirmado_com_notificacao_enviada_com_sucesso(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        rerun = MagicMock()
        monkeypatch.setattr(admin.st, "rerun", rerun)
        _patch_confirm_dialog_widgets(monkeypatch, notify=True, confirmed=True)
        approve_signup = MagicMock()
        notify_approved = MagicMock(return_value=True)
        monkeypatch.setattr(admin.infrastructure, "approve_signup", approve_signup)
        monkeypatch.setattr(admin.infrastructure, "notify_user_approved", notify_approved)

        self._run({"kind": "approve", "email": "p@x.com", "name": "P"})

        approve_signup.assert_called_once_with("p@x.com")
        notify_approved.assert_called_once_with("p@x.com", "P")
        feedback = session_state["admin_action_feedback"]
        assert feedback["kind"] == "success"
        assert feedback["text"] == "Cadastro de P (p@x.com) aprovado — e-mail enviado com sucesso."
        assert "admin_pending_action" not in session_state
        rerun.assert_called_once()

    def test_aprovar_confirmado_sem_marcar_notificar_nao_envia_email(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        monkeypatch.setattr(admin.st, "rerun", MagicMock())
        _patch_confirm_dialog_widgets(monkeypatch, notify=False, confirmed=True)
        approve_signup = MagicMock()
        notify_approved = MagicMock()
        monkeypatch.setattr(admin.infrastructure, "approve_signup", approve_signup)
        monkeypatch.setattr(admin.infrastructure, "notify_user_approved", notify_approved)

        self._run({"kind": "approve", "email": "p@x.com", "name": "P"})

        approve_signup.assert_called_once_with("p@x.com")
        notify_approved.assert_not_called()
        assert "e-mail não enviado (opção desmarcada)" in session_state["admin_action_feedback"]["text"]
        assert session_state["admin_action_feedback"]["kind"] == "success"

    def test_reprovar_confirmado_com_falha_no_envio_de_email_gera_warning(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        monkeypatch.setattr(admin.st, "rerun", MagicMock())
        _patch_confirm_dialog_widgets(monkeypatch, notify=True, confirmed=True)
        reject_signup = MagicMock()
        notify_rejected = MagicMock(return_value=False)
        monkeypatch.setattr(admin.infrastructure, "reject_signup", reject_signup)
        monkeypatch.setattr(admin.infrastructure, "notify_user_rejected", notify_rejected)

        self._run({"kind": "reject", "email": "p@x.com", "name": "P"})

        reject_signup.assert_called_once_with("p@x.com")
        feedback = session_state["admin_action_feedback"]
        assert feedback["kind"] == "warning"
        assert "falha ao enviar o e-mail" in feedback["text"]
        assert "Cadastro de P" in feedback["text"]

    def test_remover_nao_confirmado_usa_mesmo_fluxo_de_reprovar(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        monkeypatch.setattr(admin.st, "rerun", MagicMock())
        _patch_confirm_dialog_widgets(monkeypatch, notify=False, confirmed=True)
        reject_signup = MagicMock()
        monkeypatch.setattr(admin.infrastructure, "reject_signup", reject_signup)

        self._run({"kind": "remove_unconfirmed", "email": "u@x.com", "name": "U"})

        reject_signup.assert_called_once_with("u@x.com")
        feedback = session_state["admin_action_feedback"]
        assert "Cadastro não confirmado de U (u@x.com) removido" in feedback["text"]

    def test_revogar_confirmado_chama_revoke_access(self, monkeypatch):
        session_state = {}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        monkeypatch.setattr(admin.st, "rerun", MagicMock())
        _patch_confirm_dialog_widgets(monkeypatch, notify=True, confirmed=True)
        revoke_access = MagicMock()
        notify_revoked = MagicMock(return_value=True)
        monkeypatch.setattr(admin.infrastructure, "revoke_access", revoke_access)
        monkeypatch.setattr(admin.infrastructure, "notify_user_revoked", notify_revoked)

        self._run({"kind": "revoke", "email": "a@x.com", "name": "A"})

        revoke_access.assert_called_once_with("a@x.com")
        feedback = session_state["admin_action_feedback"]
        assert "Acesso de A (a@x.com) revogado" in feedback["text"]

    def test_cancelar_nao_chama_nenhuma_acao_de_infraestrutura(self, monkeypatch):
        session_state = {"admin_pending_action": {"kind": "approve", "email": "p@x.com", "name": "P"}}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        rerun = MagicMock()
        monkeypatch.setattr(admin.st, "rerun", rerun)
        _patch_confirm_dialog_widgets(monkeypatch, notify=True, cancelled=True, confirmed=False)
        approve_signup = MagicMock()
        monkeypatch.setattr(admin.infrastructure, "approve_signup", approve_signup)

        self._run({"kind": "approve", "email": "p@x.com", "name": "P"})

        approve_signup.assert_not_called()
        assert "admin_pending_action" not in session_state
        rerun.assert_called_once()

    def test_nenhum_botao_clicado_nao_faz_nada(self, monkeypatch):
        session_state = {"admin_pending_action": {"kind": "approve", "email": "p@x.com", "name": "P"}}
        monkeypatch.setattr(admin.st, "session_state", session_state)
        rerun = MagicMock()
        monkeypatch.setattr(admin.st, "rerun", rerun)
        _patch_confirm_dialog_widgets(monkeypatch, notify=True, cancelled=False, confirmed=False)
        approve_signup = MagicMock()
        monkeypatch.setattr(admin.infrastructure, "approve_signup", approve_signup)

        self._run({"kind": "approve", "email": "p@x.com", "name": "P"})

        approve_signup.assert_not_called()
        rerun.assert_not_called()
        assert "admin_pending_action" in session_state


class TestRenderAdminPanel:
    def _patch_common(self, monkeypatch, session_state):
        monkeypatch.setattr(admin.st, "session_state", session_state)
        monkeypatch.setattr(admin, "load_admin_css", MagicMock())
        monkeypatch.setattr(admin, "load_profile_css", MagicMock())
        monkeypatch.setattr(admin, "render_nav_bar", MagicMock())

    def test_secao_padrao_usuarios_chama_render_table(self, monkeypatch):
        self._patch_common(monkeypatch, {})
        render_table = MagicMock()
        monkeypatch.setattr(admin, "_render_table", render_table)
        profile_tab = MagicMock()
        password_tab = MagicMock()
        monkeypatch.setattr(admin, "render_profile_tab", profile_tab)
        monkeypatch.setattr(admin, "render_password_tab", password_tab)

        admin.render_admin_panel("1.2.3.4")

        render_table.assert_called_once()
        profile_tab.assert_not_called()
        password_tab.assert_not_called()

    def test_secao_perfil_chama_render_profile_tab_com_proprio_perfil(self, monkeypatch):
        self._patch_common(monkeypatch, {"admin_active_section": "perfil", "user_email": "admin@x.com"})
        monkeypatch.setattr(admin, "_render_table", MagicMock())
        monkeypatch.setattr(admin, "get_own_profile", lambda email: {"name": "Admin", "email": email})
        profile_tab = MagicMock()
        monkeypatch.setattr(admin, "render_profile_tab", profile_tab)
        monkeypatch.setattr(admin, "render_password_tab", MagicMock())

        admin.render_admin_panel("1.2.3.4")

        profile_tab.assert_called_once_with({"name": "Admin", "email": "admin@x.com"})

    def test_secao_senha_chama_render_password_tab(self, monkeypatch):
        self._patch_common(monkeypatch, {"admin_active_section": "senha"})
        monkeypatch.setattr(admin, "_render_table", MagicMock())
        password_tab = MagicMock()
        monkeypatch.setattr(admin, "render_password_tab", password_tab)
        monkeypatch.setattr(admin, "render_profile_tab", MagicMock())

        admin.render_admin_panel("1.2.3.4")

        password_tab.assert_called_once_with("1.2.3.4")
