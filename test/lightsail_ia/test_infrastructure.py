"""test_infrastructure.py — testes do bootstrap de processo e rate limiting do FilmBot."""

import time
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from src import infrastructure


def _client_error(code: str, operation: str = "Op") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


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

    def test_propaga_outros_codigos_de_erro(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.admin_initiate_auth.side_effect = _client_error(
                "TooManyRequestsException"
            )
            with pytest.raises(ClientError):
                infrastructure.authenticate("user@ex.com", "Senha123!")


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
    def test_filtra_por_status_unconfirmed_e_extrai_atributos(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {
                "Users": [
                    {
                        "Enabled": True,
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
            Filter='cognito:user_status = "UNCONFIRMED"',
        )
        assert resultado == [{"email": "novo@ex.com", "name": "Novo Usuário", "enabled": True}]


class TestListActiveUsers:
    def test_filtra_por_status_confirmed(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            mock_boto.return_value.list_users.return_value = {"Users": []}
            infrastructure.list_active_users()

        mock_boto.return_value.list_users.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            Filter='cognito:user_status = "CONFIRMED"',
        )


class TestApproveSignup:
    def test_confirma_cadastro_e_marca_email_como_verificado(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.approve_signup("user@ex.com")

        mock_boto.return_value.admin_confirm_sign_up.assert_called_once_with(
            UserPoolId="sa-east-1_testpool", Username="user@ex.com"
        )
        mock_boto.return_value.admin_update_user_attributes.assert_called_once_with(
            UserPoolId="sa-east-1_testpool",
            Username="user@ex.com",
            UserAttributes=[{"Name": "email_verified", "Value": "true"}],
        )


class TestRejectSignup:
    def test_exclui_a_conta(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.reject_signup("user@ex.com")

        mock_boto.return_value.admin_delete_user.assert_called_once_with(
            UserPoolId="sa-east-1_testpool", Username="user@ex.com"
        )


class TestRevokeAccess:
    def test_desativa_o_usuario(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.revoke_access("user@ex.com")

        mock_boto.return_value.admin_disable_user.assert_called_once_with(
            UserPoolId="sa-east-1_testpool", Username="user@ex.com"
        )


class TestRestoreAccess:
    def test_reativa_o_usuario(self):
        with patch("src.infrastructure.boto3.client") as mock_boto:
            infrastructure.restore_access("user@ex.com")

        mock_boto.return_value.admin_enable_user.assert_called_once_with(
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
