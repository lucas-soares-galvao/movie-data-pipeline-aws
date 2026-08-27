"""test_infrastructure.py — testes do bootstrap de processo e rate limiting do FilmBot."""

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from src import infrastructure


def _client_error(code: str, operation: str = "Op", message: str | None = None) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message if message is not None else code}}, operation)


class TestLoadFilmbotPassword:
    def test_retorna_sem_chamar_secrets_manager_quando_secret_arn_nao_configurado(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        with patch("src.infrastructure.boto3.client") as mock_client:
            infrastructure.load_filmbot_password()
        mock_client.assert_not_called()

    def test_retorna_sem_chamar_secrets_manager_quando_secrets_toml_ja_existe(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123456789012:secret:x")
        with (
            patch("src.infrastructure.Path.exists", return_value=True),
            patch("src.infrastructure.boto3.client") as mock_client,
        ):
            infrastructure.load_filmbot_password()
        mock_client.assert_not_called()


class TestSetupCloudwatchLogging:
    def test_retorna_sem_registrar_handler_quando_log_group_nao_configurado(self, monkeypatch):
        monkeypatch.delenv("CLOUDWATCH_LOG_GROUP", raising=False)
        infrastructure.setup_cloudwatch_logging.clear()
        with patch("src.infrastructure.watchtower.CloudWatchLogHandler") as mock_handler:
            infrastructure.setup_cloudwatch_logging()
        mock_handler.assert_not_called()


class TestGetClientIp:
    def test_retorna_local_quando_nao_ha_header_x_forwarded_for(self):
        assert infrastructure.get_client_ip() == "local"


class TestEventsInWindow:
    def test_conta_apenas_eventos_dentro_da_janela(self):
        agora = time.time()
        history = {"1.2.3.4": [agora - 10, agora - 3700]}

        resultado = infrastructure.events_in_window(history, "1.2.3.4", window_seconds=3600)

        assert resultado == 1

    def test_limpa_eventos_expirados_do_historico(self):
        agora = time.time()
        history = {"1.2.3.4": [agora - 10, agora - 3700]}

        infrastructure.events_in_window(history, "1.2.3.4", window_seconds=3600)

        assert history["1.2.3.4"] == [history["1.2.3.4"][0]]

    def test_retorna_zero_para_ip_sem_historico(self):
        assert infrastructure.events_in_window({}, "1.2.3.4", window_seconds=3600) == 0


class TestSecondsUntilAvailable:
    def test_retorna_zero_quando_nao_ha_historico(self):
        assert infrastructure.seconds_until_available({}, "1.2.3.4", window_seconds=60) == 0

    def test_calcula_segundos_restantes_ate_evento_mais_antigo_expirar(self):
        agora = time.time()
        history = {"1.2.3.4": [agora - 50]}

        resultado = infrastructure.seconds_until_available(history, "1.2.3.4", window_seconds=60)

        assert 9 <= resultado <= 10

    def test_retorna_zero_quando_janela_ja_expirou(self):
        agora = time.time()
        history = {"1.2.3.4": [agora - 120]}

        assert infrastructure.seconds_until_available(history, "1.2.3.4", window_seconds=60) == 0


class TestSignUp:
    def test_chama_sign_up_com_email_senha_e_nome(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.sign_up("user@ex.com", "Senha123!", "Fulano")

        mock_boto.return_value.sign_up.assert_called_once_with(
            ClientId="test-app-client-id",
            Username="user@ex.com",
            Password="Senha123!",
            UserAttributes=[
                {"Name": "email", "Value": "user@ex.com"},
                {"Name": "name", "Value": "Fulano"},
            ],
        )

    def test_nao_desabilita_a_conta_no_signup(self):
        # ConfirmSignUp exige Enabled=true para aceitar o código (testado
        # empiricamente contra o Cognito real — com Enabled=false ele rejeita
        # qualquer código, mesmo o certo, com CodeMismatchException). Desabilitar
        # aqui quebraria a própria confirmação — ver TestConfirmSignUp abaixo.
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.sign_up("user@ex.com", "Senha123!", "Fulano")

        mock_boto.return_value.admin_disable_user.assert_not_called()


class TestConfirmSignUp:
    def test_chama_confirm_sign_up_com_email_e_codigo(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.confirm_sign_up("user@ex.com", "123456")

        mock_boto.return_value.confirm_sign_up.assert_called_once_with(
            ClientId="test-app-client-id",
            Username="user@ex.com",
            ConfirmationCode="123456",
        )

    def test_desabilita_a_conta_depois_de_confirmar(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.confirm_sign_up("user@ex.com", "123456")

        mock_boto.return_value.admin_disable_user.assert_called_once_with(
            UserPoolId="sa-east-1_testpool", Username="user@ex.com"
        )

    def test_nao_desabilita_a_conta_quando_confirm_sign_up_falha(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.confirm_sign_up.side_effect = _client_error("CodeMismatchException")
            with pytest.raises(ClientError):
                infrastructure.confirm_sign_up("user@ex.com", "000000")

        mock_boto.return_value.admin_disable_user.assert_not_called()


class TestResendConfirmationCode:
    def test_chama_resend_confirmation_code_com_email(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.resend_confirmation_code("user@ex.com")

        mock_boto.return_value.resend_confirmation_code.assert_called_once_with(
            ClientId="test-app-client-id", Username="user@ex.com"
        )


class TestAuthenticate:
    def test_retorna_ok_quando_credenciais_corretas(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            resultado = infrastructure.authenticate("user@ex.com", "Senha123!")

        assert resultado == "ok"
        mock_boto.return_value.admin_initiate_auth.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            ClientId="test-app-client-id",
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": "user@ex.com", "PASSWORD": "Senha123!"},
        )

    def test_retorna_pending_quando_cadastro_ainda_nao_aprovado(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.admin_initiate_auth.side_effect = _client_error(
                "UserNotConfirmedException"
            )
            resultado = infrastructure.authenticate("user@ex.com", "Senha123!")

        assert resultado == "pending"

    @pytest.mark.parametrize("codigo", ["NotAuthorizedException", "UserNotFoundException"])
    def test_retorna_invalid_para_credenciais_incorretas_ou_usuario_inexistente(self, codigo):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.admin_initiate_auth.side_effect = _client_error(codigo)
            resultado = infrastructure.authenticate("user@ex.com", "Senha123!")

        assert resultado == "invalid"

    def test_retorna_pending_quando_conta_esta_desabilitada_aguardando_aprovacao(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.admin_initiate_auth.side_effect = _client_error(
                "NotAuthorizedException", message="User is disabled."
            )
            resultado = infrastructure.authenticate("user@ex.com", "Senha123!")

        assert resultado == "pending"

    def test_propaga_outros_codigos_de_erro(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.admin_initiate_auth.side_effect = _client_error(
                "TooManyRequestsException"
            )
            with pytest.raises(ClientError):
                infrastructure.authenticate("user@ex.com", "Senha123!")


class TestRecordLogin:
    def test_grava_timestamp_iso_utc_no_atributo_custom_last_login(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.record_login("user@ex.com")

        mock_boto.return_value.admin_update_user_attributes.assert_called_once()
        _, kwargs = mock_boto.return_value.admin_update_user_attributes.call_args
        assert kwargs["UserPoolId"] == "sa-east-1_testpool"
        assert kwargs["Username"] == "user@ex.com"
        [attribute] = kwargs["UserAttributes"]
        assert attribute["Name"] == "custom:last_login"
        # Valida que o valor gravado é um ISO 8601 parseável (não compara string exata,
        # já que o timestamp é gerado no momento da chamada).
        datetime.fromisoformat(attribute["Value"])


class TestRecordPasswordUpdate:
    def test_grava_timestamp_iso_utc_no_atributo_custom_password_updated_at(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.record_password_update("user@ex.com")

        mock_boto.return_value.admin_update_user_attributes.assert_called_once()
        _, kwargs = mock_boto.return_value.admin_update_user_attributes.call_args
        assert kwargs["UserPoolId"] == "sa-east-1_testpool"
        assert kwargs["Username"] == "user@ex.com"
        [attribute] = kwargs["UserAttributes"]
        assert attribute["Name"] == "custom:password_updated_at"
        datetime.fromisoformat(attribute["Value"])


class TestGetUserProfile:
    def test_busca_por_email_e_extrai_atributos(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {
                "Users": [
                    {
                        "Enabled": True,
                        "UserStatus": "CONFIRMED",
                        "UserCreateDate": datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                        "Attributes": [
                            {"Name": "email", "Value": "user@ex.com"},
                            {"Name": "name", "Value": "Usuário Teste"},
                        ],
                    }
                ]
            }
            resultado = infrastructure.get_user_profile("user@ex.com")

        mock_boto.return_value.list_users.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            Filter='email = "user@ex.com"',
        )
        assert resultado["name"] == "Usuário Teste"
        assert resultado["email"] == "user@ex.com"


class TestUpdateUserName:
    def test_grava_nome_no_atributo_name(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.update_user_name("user@ex.com", "Novo Nome")

        mock_boto.return_value.admin_update_user_attributes.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            Username="user@ex.com",
            UserAttributes=[{"Name": "name", "Value": "Novo Nome"}],
        )


class TestChangePassword:
    def test_retorna_ok_e_define_senha_nova_quando_senha_atual_correta(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            resultado = infrastructure.change_password("user@ex.com", "SenhaAtual1!", "SenhaNova1!")

        assert resultado == "ok"
        mock_boto.return_value.admin_set_user_password.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            Username="user@ex.com",
            Password="SenhaNova1!",
            Permanent=True,
        )

    def test_retorna_invalid_sem_definir_senha_quando_senha_atual_incorreta(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.admin_initiate_auth.side_effect = _client_error(
                "NotAuthorizedException"
            )
            resultado = infrastructure.change_password("user@ex.com", "SenhaErrada", "SenhaNova1!")

        assert resultado == "invalid"
        mock_boto.return_value.admin_set_user_password.assert_not_called()


class TestIsAdmin:
    def test_retorna_true_quando_usuario_pertence_ao_grupo_admins(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.admin_list_groups_for_user.return_value = {
                "Groups": [{"GroupName": "admins"}]
            }
            assert infrastructure.is_admin("user@ex.com") is True

    def test_retorna_false_quando_usuario_nao_pertence_ao_grupo_admins(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.admin_list_groups_for_user.return_value = {"Groups": []}
            assert infrastructure.is_admin("user@ex.com") is False


class TestGetUserStatus:
    def test_retorna_user_status_quando_lista_de_usuarios_nao_esta_vazia(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {
                "Users": [{"Attributes": [], "UserStatus": "UNCONFIRMED"}]
            }
            assert infrastructure.get_user_status("user@ex.com") == "UNCONFIRMED"

        mock_boto.return_value.list_users.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            Filter='email = "user@ex.com"',
        )

    def test_retorna_none_quando_lista_de_usuarios_esta_vazia(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {"Users": []}
            assert infrastructure.get_user_status("naocadastrado@ex.com") is None

    def test_retorna_none_sem_chamar_a_api_quando_email_contem_aspas(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            assert infrastructure.get_user_status('a"@ex.com') is None
            mock_boto.return_value.list_users.assert_not_called()


class TestRequestPasswordReset:
    def test_chama_forgot_password_com_email(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.request_password_reset("user@ex.com")

        mock_boto.return_value.forgot_password.assert_called_once_with(
            ClientId="test-app-client-id", Username="user@ex.com"
        )


class TestConfirmPasswordReset:
    def test_chama_confirm_forgot_password_com_codigo_e_nova_senha(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.confirm_password_reset("user@ex.com", "123456", "NovaSenha123!")

        mock_boto.return_value.confirm_forgot_password.assert_called_once_with(
            ClientId="test-app-client-id",
            Username="user@ex.com",
            ConfirmationCode="123456",
            Password="NovaSenha123!",
        )


class TestListPendingUsers:
    def test_filtra_por_status_disabled_e_extrai_atributos(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {
                "Users": [
                    {
                        "Enabled": False,
                        "UserStatus": "CONFIRMED",
                        "UserCreateDate": datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                        "Attributes": [
                            {"Name": "email", "Value": "novo@ex.com"},
                            {"Name": "name", "Value": "Novo Usuário"},
                        ],
                    }
                ]
            }
            resultado = infrastructure.list_pending_users()

        mock_boto.return_value.list_users.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            Filter='status = "Disabled"',
        )
        assert resultado == [
            {
                "email": "novo@ex.com",
                "name": "Novo Usuário",
                "enabled": False,
                "created_at": "2026-08-01T10:00:00+00:00",
                "updated_at": "",
                "last_login": "",
            }
        ]

    def test_extrai_last_login_quando_atributo_custom_existe(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {
                "Users": [
                    {
                        "Enabled": False,
                        "UserStatus": "CONFIRMED",
                        "UserCreateDate": datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                        "Attributes": [
                            {"Name": "email", "Value": "ativo@ex.com"},
                            {"Name": "name", "Value": "Usuário Ativo"},
                            {"Name": "custom:last_login", "Value": "2026-08-23T12:00:00+00:00"},
                        ],
                    }
                ]
            }
            resultado = infrastructure.list_pending_users()

        assert resultado[0]["last_login"] == "2026-08-23T12:00:00+00:00"

    def test_extrai_updated_at_quando_atributo_custom_existe(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {
                "Users": [
                    {
                        "Enabled": False,
                        "UserStatus": "CONFIRMED",
                        "UserCreateDate": datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                        "Attributes": [
                            {"Name": "email", "Value": "ativo@ex.com"},
                            {"Name": "name", "Value": "Usuário Ativo"},
                            {"Name": "custom:password_updated_at", "Value": "2026-08-23T12:00:00+00:00"},
                        ],
                    }
                ]
            }
            resultado = infrastructure.list_pending_users()

        assert resultado[0]["updated_at"] == "2026-08-23T12:00:00+00:00"

    def test_descarta_usuarios_que_ainda_nao_confirmaram_o_email(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {
                "Users": [
                    {
                        "Enabled": False,
                        "UserStatus": "CONFIRMED",
                        "UserCreateDate": datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                        "Attributes": [
                            {"Name": "email", "Value": "confirmado@ex.com"},
                            {"Name": "name", "Value": "Confirmado"},
                        ],
                    },
                    {
                        "Enabled": False,
                        "UserStatus": "UNCONFIRMED",
                        "UserCreateDate": datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                        "Attributes": [
                            {"Name": "email", "Value": "aindanaoconfirmou@ex.com"},
                            {"Name": "name", "Value": "Ainda Não Confirmou"},
                        ],
                    },
                ]
            }
            resultado = infrastructure.list_pending_users()

        assert [user["email"] for user in resultado] == ["confirmado@ex.com"]


class TestListActiveUsers:
    def test_filtra_por_status_enabled(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {"Users": []}
            infrastructure.list_active_users()

        mock_boto.return_value.list_users.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            Filter='status = "Enabled"',
        )

    def test_descarta_usuarios_ainda_nao_confirmados_por_defesa(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {
                "Users": [
                    {
                        "Enabled": True,
                        "UserStatus": "CONFIRMED",
                        "UserCreateDate": datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                        "Attributes": [
                            {"Name": "email", "Value": "ativo@ex.com"},
                            {"Name": "name", "Value": "Ativo"},
                        ],
                    },
                    {
                        "Enabled": True,
                        "UserStatus": "UNCONFIRMED",
                        "UserCreateDate": datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                        "Attributes": [
                            {"Name": "email", "Value": "inesperado@ex.com"},
                            {"Name": "name", "Value": "Inesperado"},
                        ],
                    },
                ]
            }
            resultado = infrastructure.list_active_users()

        assert [user["email"] for user in resultado] == ["ativo@ex.com"]


class TestApproveSignup:
    def test_habilita_a_conta(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.approve_signup("user@ex.com")

        mock_boto.return_value.admin_enable_user.assert_called_once_with(
            UserPoolId="sa-east-1_testpool", Username="user@ex.com"
        )


class TestRejectSignup:
    def test_exclui_a_conta(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.reject_signup("user@ex.com")

        mock_boto.return_value.admin_delete_user.assert_called_once_with(
            UserPoolId="sa-east-1_testpool", Username="user@ex.com"
        )


class TestRevokeAccess:
    def test_exclui_a_conta(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.revoke_access("user@ex.com")

        mock_boto.return_value.admin_delete_user.assert_called_once_with(
            UserPoolId="sa-east-1_testpool", Username="user@ex.com"
        )


class TestAddToAdminsGroup:
    def test_adiciona_usuario_ao_grupo_admins(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.add_to_admins_group("admin@ex.com")

        mock_boto.return_value.admin_add_user_to_group.assert_called_once_with(
            UserPoolId="sa-east-1_testpool", Username="admin@ex.com", GroupName="admins"
        )


class TestNotifyNewSignup:
    def test_publica_no_topico_sns_com_email_e_nome(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.notify_new_signup("user@ex.com", "Fulano")

        mock_boto.return_value.publish.assert_called_once_with(
            TopicArn="arn:aws:sns:sa-east-1:123456789012:test-new-signup-topic",
            Subject="FilmBot — cadastro novo pendente de aprovação",
            Message="Fulano (user@ex.com) acabou de se cadastrar no FilmBot e está aguardando aprovação.",
        )


class TestNotifyUserApproved:
    def test_nao_chama_smtp_quando_nenhuma_credencial_esta_configurada(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.delenv("GMAIL_SENDER_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        with patch("src.infrastructure.smtplib.SMTP_SSL") as mock_smtp:
            infrastructure.notify_user_approved("user@ex.com", "Fulano")

        mock_smtp.assert_not_called()

    def test_envia_email_com_credenciais_do_secrets_manager(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123456789012:secret:x")
        mock_secrets_client = MagicMock()
        mock_secrets_client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {"gmail_sender_email": "filmbot.lsgalvao@gmail.com", "gmail_app_password": "abcd efgh ijkl mnop"}
            )
        }
        mock_smtp_server = MagicMock()

        with (
            patch("src.infrastructure.boto3.client", return_value=mock_secrets_client),
            patch("src.infrastructure.smtplib.SMTP_SSL") as mock_smtp,
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp_server
            infrastructure.notify_user_approved("user@ex.com", "Fulano")

        mock_secrets_client.get_secret_value.assert_called_once_with(
            SecretId="arn:aws:secretsmanager:sa-east-1:123456789012:secret:x"
        )
        mock_smtp.assert_called_once_with("smtp.gmail.com", 465)
        mock_smtp_server.login.assert_called_once_with("filmbot.lsgalvao@gmail.com", "abcd efgh ijkl mnop")
        mock_smtp_server.send_message.assert_called_once()
        sent_message = mock_smtp_server.send_message.call_args[0][0]
        assert sent_message["Subject"] == "FilmBot — cadastro aprovado"
        assert sent_message["From"] == "filmbot.lsgalvao@gmail.com"
        assert sent_message["To"] == "user@ex.com"
        body = sent_message.get_payload(decode=True).decode(sent_message.get_content_charset())
        assert "Fulano" in body
        assert "https://filmbot.lsgalvao.com.br" in body
        assert "user@ex.com" in body

    def test_envia_email_com_fallback_de_env_vars_quando_secret_arn_nao_configurado(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")
        mock_smtp_server = MagicMock()

        with (
            patch("src.infrastructure.boto3.client") as mock_boto,
            patch("src.infrastructure.smtplib.SMTP_SSL") as mock_smtp,
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp_server
            infrastructure.notify_user_approved("user@ex.com", "Fulano")

        mock_boto.assert_not_called()
        mock_smtp_server.login.assert_called_once_with("filmbot.lsgalvao@gmail.com", "senha-de-app")
        mock_smtp_server.send_message.assert_called_once()

    def test_cai_para_fallback_de_env_vars_quando_secret_nao_tem_as_chaves_gmail(self, monkeypatch):
        monkeypatch.setenv("FILMBOT_SECRET_ARN", "arn:aws:secretsmanager:sa-east-1:123456789012:secret:x")
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")
        mock_secrets_client = MagicMock()
        mock_secrets_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"llm_api_key": "sk-outra-coisa"})
        }
        mock_smtp_server = MagicMock()

        with (
            patch("src.infrastructure.boto3.client", return_value=mock_secrets_client),
            patch("src.infrastructure.smtplib.SMTP_SSL") as mock_smtp,
        ):
            mock_smtp.return_value.__enter__.return_value = mock_smtp_server
            infrastructure.notify_user_approved("user@ex.com", "Fulano")

        mock_smtp_server.login.assert_called_once_with("filmbot.lsgalvao@gmail.com", "senha-de-app")

    def test_loga_erro_sem_propagar_quando_smtp_falha(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")

        with patch("src.infrastructure.smtplib.SMTP_SSL", side_effect=OSError("conexão recusada")):
            infrastructure.notify_user_approved("user@ex.com", "Fulano")


class TestNotifyUserRejected:
    def test_envia_email_com_assunto_e_corpo_de_reprovacao(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")
        mock_smtp_server = MagicMock()

        with patch("src.infrastructure.smtplib.SMTP_SSL") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp_server
            infrastructure.notify_user_rejected("user@ex.com", "Fulano")

        mock_smtp_server.login.assert_called_once_with("filmbot.lsgalvao@gmail.com", "senha-de-app")
        sent_message = mock_smtp_server.send_message.call_args[0][0]
        assert sent_message["Subject"] == "FilmBot — cadastro não aprovado"
        assert sent_message["To"] == "user@ex.com"
        body = sent_message.get_payload(decode=True).decode(sent_message.get_content_charset())
        assert "Fulano" in body
        assert "não foi aprovado" in body

    def test_nao_chama_smtp_quando_nenhuma_credencial_esta_configurada(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.delenv("GMAIL_SENDER_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        with patch("src.infrastructure.smtplib.SMTP_SSL") as mock_smtp:
            infrastructure.notify_user_rejected("user@ex.com", "Fulano")

        mock_smtp.assert_not_called()


class TestNotifyUserRevoked:
    def test_envia_email_com_assunto_e_corpo_de_revogacao(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.setenv("GMAIL_SENDER_EMAIL", "filmbot.lsgalvao@gmail.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-de-app")
        mock_smtp_server = MagicMock()

        with patch("src.infrastructure.smtplib.SMTP_SSL") as mock_smtp:
            mock_smtp.return_value.__enter__.return_value = mock_smtp_server
            infrastructure.notify_user_revoked("user@ex.com", "Fulano")

        mock_smtp_server.login.assert_called_once_with("filmbot.lsgalvao@gmail.com", "senha-de-app")
        sent_message = mock_smtp_server.send_message.call_args[0][0]
        assert sent_message["Subject"] == "FilmBot — acesso revogado"
        assert sent_message["To"] == "user@ex.com"
        body = sent_message.get_payload(decode=True).decode(sent_message.get_content_charset())
        assert "Fulano" in body
        assert "revogado" in body

    def test_nao_chama_smtp_quando_nenhuma_credencial_esta_configurada(self, monkeypatch):
        monkeypatch.delenv("FILMBOT_SECRET_ARN", raising=False)
        monkeypatch.delenv("GMAIL_SENDER_EMAIL", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        with patch("src.infrastructure.smtplib.SMTP_SSL") as mock_smtp:
            infrastructure.notify_user_revoked("user@ex.com", "Fulano")

        mock_smtp.assert_not_called()
