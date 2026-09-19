"""test_app.py — testes do entrypoint Streamlit (app.py) via streamlit.testing.v1.AppTest.

app.py roda tudo a nível de módulo na importação (sem nenhuma função isolada para
chamar diretamente) — por isso é o único módulo de lightsail_ia que precisa do
framework AppTest (primeiro uso no projeto) em vez do padrão de mock direto de
`st.*` usado no resto da suíte. AppTest executa o script de verdade a cada
`.run()`/`.click().run()` — os `from src.X import Y` de app.py são resolvidos de
novo em cada execução, então basta o monkeypatch estar aplicado no módulo de
origem (`admin.render_admin_panel`, etc.) antes de chamar `.run()`.

CUIDADO validado manualmente antes de escrever este arquivo: sem mockar
`render_admin_panel`/`render_profile_panel`, o app tenta chamar a API real do
Cognito (`list_pending_users`/`get_own_profile`) assim que a tela renderiza — e
se a máquina tiver credenciais AWS ambiente configuradas, isso dispara uma
chamada de rede real. Por isso este arquivo sempre mocka os 5 `render_*`
delegados antes de qualquer `.run()`.

`infrastructure.get_client_ip`/`load_filmbot_password`/`setup_cloudwatch_logging`
NÃO são mockados de propósito: o mecanismo de alias `src.*` do conftest global
(necessário para várias suites de teste compartilharem o mesmo processo pytest)
carrega `infrastructure` (importado internamente por `recommendation.py`, o
módulo-âncora da suíte) por um caminho de import diferente do resto — o
monkeypatch aplicado nesse objeto não é o mesmo que `app.py` resolve durante
`.run()` do AppTest (confirmado isolando o caso: `render_admin_panel`/
`render_profile_panel`/`render_recommendation`/`render_cards`/`render_footer`
respeitam o monkeypatch normalmente, só `infrastructure` diverge). As três
funções já são seguras de rodar de verdade em teste: sem `FILMBOT_SECRET_ARN`/
`CLOUDWATCH_LOG_GROUP` no ambiente, `load_filmbot_password`/
`setup_cloudwatch_logging` retornam sem tocar AWS (mesmo comportamento já
validado em `test_infrastructure.py`), e `get_client_ip()` sem header
`X-Forwarded-For` real (nunca presente no AppTest) sempre retorna `"local"` —
por isso os testes abaixo comparam contra `"local"`, não um IP arbitrário.
"""

from pathlib import Path
from unittest.mock import MagicMock

from src import admin, cards, components, profile, recommendation
from streamlit.testing.v1 import AppTest

_APP_PATH = str(Path(__file__).resolve().parents[2] / "app" / "lightsail_ia" / "app.py")
_CLIENT_IP = "local"


def _new_app_test(monkeypatch, initial_state: dict | None = None):
    mocks = {
        "render_admin_panel": MagicMock(),
        "render_profile_panel": MagicMock(),
        "render_recommendation": MagicMock(),
        "render_cards": MagicMock(),
        "render_footer": MagicMock(),
    }
    monkeypatch.setattr(admin, "render_admin_panel", mocks["render_admin_panel"])
    monkeypatch.setattr(profile, "render_profile_panel", mocks["render_profile_panel"])
    monkeypatch.setattr(recommendation, "render_recommendation", mocks["render_recommendation"])
    monkeypatch.setattr(cards, "render_cards", mocks["render_cards"])
    monkeypatch.setattr(components, "render_footer", mocks["render_footer"])

    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    for key, value in (initial_state or {}).items():
        at.session_state[key] = value
    return at, mocks


class TestGateDeAutenticacao:
    def test_nao_autenticado_mostra_login_e_nao_renderiza_header(self, monkeypatch):
        at, mocks = _new_app_test(monkeypatch)

        at.run()

        assert not at.exception
        # render_forms real (não mockado) renderiza o login de verdade e chama
        # st.stop() — nada depois disso (header/dispatch) deve executar.
        assert {b.key for b in at.button} == {"btn_entrar", "btn_link_esqueci", "btn_link_cadastro"}
        mocks["render_recommendation"].assert_not_called()
        mocks["render_cards"].assert_not_called()
        mocks["render_footer"].assert_not_called()


class TestDispatchPrincipal:
    def test_nao_admin_sem_view_mostra_recomendacao_e_cards(self, monkeypatch):
        at, mocks = _new_app_test(monkeypatch, {"authenticated": True, "is_admin": False})

        at.run()

        assert not at.exception
        mocks["render_recommendation"].assert_called_once_with(_CLIENT_IP)
        mocks["render_cards"].assert_called_once()
        mocks["render_admin_panel"].assert_not_called()
        mocks["render_profile_panel"].assert_not_called()
        mocks["render_footer"].assert_called_once()

    def test_nao_admin_view_profile_mostra_perfil(self, monkeypatch):
        at, mocks = _new_app_test(monkeypatch, {
            "authenticated": True, "is_admin": False, "current_view": "profile",
        })

        at.run()

        mocks["render_profile_panel"].assert_called_once_with(_CLIENT_IP)
        mocks["render_recommendation"].assert_not_called()
        mocks["render_cards"].assert_not_called()

    def test_admin_sem_view_mostra_recomendacao_e_cards(self, monkeypatch):
        at, mocks = _new_app_test(monkeypatch, {"authenticated": True, "is_admin": True})

        at.run()

        mocks["render_recommendation"].assert_called_once()
        mocks["render_admin_panel"].assert_not_called()

    def test_admin_view_admin_mostra_painel(self, monkeypatch):
        at, mocks = _new_app_test(monkeypatch, {
            "authenticated": True, "is_admin": True, "current_view": "admin",
        })

        at.run()

        mocks["render_admin_panel"].assert_called_once_with(_CLIENT_IP)
        mocks["render_recommendation"].assert_not_called()

    def test_view_admin_sem_ser_admin_e_ignorado(self, monkeypatch):
        # current_view="admin" sem is_admin=True (ex.: sobra de sessão anterior) não deve
        # abrir o painel — o dispatch exige "is_admin and current_view == 'admin'" junto.
        at, mocks = _new_app_test(monkeypatch, {
            "authenticated": True, "is_admin": False, "current_view": "admin",
        })

        at.run()

        mocks["render_admin_panel"].assert_not_called()
        mocks["render_recommendation"].assert_called_once()


class TestBarraDeNavegacao:
    def test_admin_ve_botao_painel_admin_nao_meu_perfil(self, monkeypatch):
        at, _ = _new_app_test(monkeypatch, {"authenticated": True, "is_admin": True})

        at.run()

        keys = {b.key for b in at.button}
        assert "btn_toggle_admin" in keys
        assert "btn_toggle_profile" not in keys
        assert at.button(key="btn_toggle_admin").label == "Painel Admin"

    def test_nao_admin_ve_botao_meu_perfil_nao_painel_admin(self, monkeypatch):
        at, _ = _new_app_test(monkeypatch, {"authenticated": True, "is_admin": False})

        at.run()

        keys = {b.key for b in at.button}
        assert "btn_toggle_profile" in keys
        assert "btn_toggle_admin" not in keys
        assert at.button(key="btn_toggle_profile").label == "Meu Perfil"

    def test_clique_no_toggle_admin_alterna_para_painel_e_de_volta(self, monkeypatch):
        at, _ = _new_app_test(monkeypatch, {"authenticated": True, "is_admin": True})
        at.run()

        at.button(key="btn_toggle_admin").click().run()
        assert at.session_state["current_view"] == "admin"
        assert at.button(key="btn_toggle_admin").label == "← App"

        at.button(key="btn_toggle_admin").click().run()
        assert at.session_state["current_view"] == "app"

    def test_clique_no_toggle_perfil_alterna_para_perfil_e_de_volta(self, monkeypatch):
        at, _ = _new_app_test(monkeypatch, {"authenticated": True, "is_admin": False})
        at.run()

        at.button(key="btn_toggle_profile").click().run()
        assert at.session_state["current_view"] == "profile"
        assert at.button(key="btn_toggle_profile").label == "← App"

        at.button(key="btn_toggle_profile").click().run()
        assert at.session_state["current_view"] == "app"

    def test_clique_em_sair_limpa_toda_a_sessao(self, monkeypatch):
        at, _ = _new_app_test(monkeypatch, {
            "authenticated": True, "is_admin": False, "user_name": "Ana", "titles": [{"title": "X"}],
        })
        at.run()

        at.button(key="btn_sair").click().run()

        assert not at.exception
        assert "authenticated" not in at.session_state
        assert "titles" not in at.session_state
        assert "user_name" not in at.session_state
