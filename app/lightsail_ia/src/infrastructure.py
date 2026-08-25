"""infrastructure.py — bootstrap de processo e utilitários de rate limiting do FilmBot."""

import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
import streamlit as st
import watchtower
from botocore.exceptions import ClientError


def load_filmbot_password() -> None:
    """Busca filmbot_password do Secrets Manager e escreve em secrets.toml."""
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if not secret_arn:
        return
    secrets_dir = Path(__file__).parent.parent / ".streamlit"
    secrets_file = secrets_dir / "secrets.toml"
    if secrets_file.exists():
        return
    client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "sa-east-1"))
    response = client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])
    secrets_dir.mkdir(exist_ok=True)
    secrets_file.write_text(
        f'[auth]\npassword = "{secret["filmbot_password"]}"\n',
        encoding="utf-8",
    )
    secrets_file.chmod(0o600)


@st.cache_resource
def setup_cloudwatch_logging() -> None:
    """Registra o handler de CloudWatch no root logger uma única vez por processo.

    O Streamlit reexecuta o script inteiro a cada rerun (clique, st.rerun(),
    etc.) — sem @st.cache_resource, este bloco rodaria a cada rerun e
    acumularia um CloudWatchLogHandler novo no root logger por vez (cada um
    com seu próprio cliente boto3, fila e thread de background), sem nunca
    remover os anteriores. Resultado: vazamento de memória progressivo e
    cada log duplicado uma vez por handler acumulado. Mesmo padrão de
    "roda uma vez por processo" já usado nas factories de histórico abaixo.
    """
    log_group = os.getenv("CLOUDWATCH_LOG_GROUP", "")
    if not log_group:
        return
    cw_handler = watchtower.CloudWatchLogHandler(
        log_group_name=log_group,
        boto3_client=boto3.client("logs", region_name=os.getenv("AWS_REGION", "sa-east-1")),
        create_log_group=False,
    )
    logging.root.addHandler(cw_handler)
    logging.root.setLevel(logging.ERROR)


def get_client_ip() -> str:
    """Extrai o IP do cliente a partir do header X-Forwarded-For repassado pelo Caddy."""
    # Confiar no primeiro valor só é seguro porque o Caddyfile sobrescreve X-Forwarded-For
    # (header_up) em vez de anexar — do contrário um cliente poderia forjar esse valor e
    # burlar o rate limit por IP abaixo.
    forwarded = st.context.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else "local"


def events_in_window(history: dict[str, list[float]], ip: str, window_seconds: int) -> int:
    """Conta eventos dentro da janela de tempo (em segundos) para o IP no histórico
    informado e limpa registros expirados. Reusada para consultas, transcrições
    e tentativas de login incorretas, cada uma com seu próprio dict de histórico."""
    now = time.time()
    filtered = [t for t in history.get(ip, []) if t > now - window_seconds]
    history[ip] = filtered
    return len(filtered)


def seconds_until_available(history: dict[str, list[float]], ip: str, window_seconds: int) -> int:
    """Calcula quantos segundos faltam até o evento mais antigo do IP expirar, na janela
    de tempo (em segundos) informada."""
    entries = history.get(ip, [])
    if not entries:
        return 0
    return max(0, math.ceil(entries[0] + window_seconds - time.time()))


def _cognito_client():  # type: ignore[no-untyped-def]
    """Cliente boto3 do Cognito Identity Provider, mesmo padrão de client factory inline
    já usado por load_filmbot_password/setup_cloudwatch_logging."""
    return boto3.client("cognito-idp", region_name=os.getenv("AWS_REGION", "sa-east-1"))


def sign_up(email: str, password: str, name: str) -> None:
    """Cadastra um novo usuário no Cognito (SignUp) e já deixa a conta desabilitada
    (AdminDisableUser) até o admin aprovar (ver approve_signup).

    O primeiro código de confirmação de e-mail é enviado automaticamente como efeito
    colateral do próprio SignUp — o pool tem auto_verified_attributes=["email"] +
    verification_message_template configurados (infra/lightsail_ia.tf); diferente do
    reset de senha (request_password_reset), não existe uma chamada explícita de
    "enviar código" aqui.

    Desabilitar a conta já neste ponto (não só na aprovação) é obrigatório: sem isso,
    assim que o usuário confirmasse o e-mail (confirm_sign_up) o UserStatus viraria
    CONFIRMED e ele conseguiria logar direto, pulando a aprovação manual do admin —
    authenticate() não teria mais nenhum outro sinal para barrar."""
    client = _cognito_client()
    client.sign_up(
        ClientId=os.environ["COGNITO_APP_CLIENT_ID"],
        Username=email,
        Password=password,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "name", "Value": name},
        ],
    )
    client.admin_disable_user(UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email)


def confirm_sign_up(email: str, code: str) -> None:
    """Confirma a posse do e-mail do cadastro (ConfirmSignUp) — o UserStatus vira
    CONFIRMED e, por "email" estar em auto_verified_attributes (infra/lightsail_ia.tf),
    o Cognito marca email_verified=true sozinho nesse momento (comportamento padrão de
    auto-verified attribute ligado ao código de confirmação do SignUp).

    Não reabilita a conta — ela continua Disabled (ver sign_up()) até o admin aprovar
    em approve_signup(). Exceptions relevantes: CodeMismatchException,
    ExpiredCodeException, LimitExceededException, TooManyFailedAttemptsException,
    AliasExistsException, UserNotFoundException (ver _signup_code_error_message em
    login.py para o mapeamento de mensagem)."""
    _cognito_client().confirm_sign_up(
        ClientId=os.environ["COGNITO_APP_CLIENT_ID"],
        Username=email,
        ConfirmationCode=code,
    )


def resend_confirmation_code(email: str) -> None:
    """Reenvia o código de confirmação de e-mail do cadastro (ResendConfirmationCode)
    — invalida o código anterior. Mesmo papel de request_password_reset() no fluxo de
    reset de senha, mas aqui é sempre um reenvio explícito: o primeiro código já saiu
    como efeito colateral de sign_up()."""
    _cognito_client().resend_confirmation_code(
        ClientId=os.environ["COGNITO_APP_CLIENT_ID"], Username=email
    )


_INVALID_LOGIN_ERROR_CODES = {"NotAuthorizedException", "UserNotFoundException"}
_DISABLED_USER_MESSAGE = "User is disabled."


def authenticate(email: str, password: str) -> str:
    """Valida e-mail/senha contra o Cognito (AdminInitiateAuth).

    Retorna "ok", "pending" (ainda não confirmou o e-mail — UserStatus Unconfirmed —
    OU já confirmou mas a conta segue desabilitada aguardando aprovação do admin) ou
    "invalid" (e-mail/senha incorretos). Outros códigos de erro (ex.: throttling)
    propagam para o chamador — só os esperados em uso normal viram um retorno tratado.

    O caso "conta desabilitada" é detectado pela mensagem do NotAuthorizedException
    (o Cognito não usa um Code dedicado para isso) — checado antes do fallback
    genérico em _INVALID_LOGIN_ERROR_CODES (que também cobre NotAuthorizedException,
    para senha incorreta), para não colidir. Essa string não é um contrato
    documentado da API — se a AWS mudar o texto no futuro, o pior caso é essa branch
    nunca bater e o usuário ver "e-mail ou senha incorretos" em vez de "aguardando
    aprovação": degradação segura, não uma falha de segurança."""
    try:
        _cognito_client().admin_initiate_auth(
            UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
            ClientId=os.environ["COGNITO_APP_CLIENT_ID"],
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
        return "ok"
    except ClientError as error:
        code = error.response["Error"]["Code"]
        message = error.response["Error"].get("Message", "")
        if code == "UserNotConfirmedException":
            return "pending"
        if code == "NotAuthorizedException" and message == _DISABLED_USER_MESSAGE:
            return "pending"
        if code in _INVALID_LOGIN_ERROR_CODES:
            return "invalid"
        raise


def record_login(email: str) -> None:
    """Grava o timestamp (ISO 8601 UTC) do login bem-sucedido no atributo custom
    `custom:last_login` (infra/lightsail_ia.tf), lido de volta por _parse_user()
    para a coluna "Último acesso" do painel admin. Chamado por login.py logo após
    um authenticate() com retorno "ok"."""
    _cognito_client().admin_update_user_attributes(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Username=email,
        UserAttributes=[{"Name": "custom:last_login", "Value": datetime.now(timezone.utc).isoformat()}],
    )


def is_admin(email: str) -> bool:
    """True se o e-mail pertence ao grupo "admins" do Cognito (ver
    infra/lightsail_ia.tf:aws_cognito_user_group.admins)."""
    response = _cognito_client().admin_list_groups_for_user(
        Username=email, UserPoolId=os.environ["COGNITO_USER_POOL_ID"]
    )
    return any(group["GroupName"] == "admins" for group in response["Groups"])


def get_user_status(email: str) -> str | None:
    """Retorna o UserStatus do Cognito (ex.: "UNCONFIRMED", "CONFIRMED") para o e-mail,
    ou None se não existe nenhuma conta com esse e-mail.

    O e-mail entra sem escapar na sintaxe de `Filter` do ListUsers — um `"` nele quebraria
    a expressão. Nenhum e-mail real contém aspas, então trata como "não existe" sem
    chamar a API (a sintaxe de Filter do Cognito não documenta escaping de aspas)."""
    if '"' in email:
        return None
    response = _cognito_client().list_users(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Filter=f'email = "{email}"',
    )
    users = response["Users"]
    return users[0]["UserStatus"] if users else None


def request_password_reset(email: str) -> None:
    """Dispara o código de recuperação de senha (ForgotPassword) — o Cognito gera,
    envia e expira o código sozinho, usando o remetente nativo dele (sem SES). Só
    funciona se o e-mail já estiver marcado como verificado, o que acontece na
    aprovação do cadastro (ver approve_signup)."""
    _cognito_client().forgot_password(ClientId=os.environ["COGNITO_APP_CLIENT_ID"], Username=email)


def confirm_password_reset(email: str, code: str, new_password: str) -> None:
    """Valida o código de recuperação de senha e define a nova senha
    (ConfirmForgotPassword)."""
    _cognito_client().confirm_forgot_password(
        ClientId=os.environ["COGNITO_APP_CLIENT_ID"],
        Username=email,
        ConfirmationCode=code,
        Password=new_password,
    )


def _parse_user(user: dict) -> dict:
    """Extrai email/name/enabled/last_login de um item retornado por list_users
    (Attributes vem como lista de {Name, Value}, não como dict). `last_login` vem
    vazio para quem nunca logou desde que o atributo custom:last_login existe
    (cadastros antigos, ou cadastros pendentes que nunca completaram login)."""
    attrs = {attr["Name"]: attr["Value"] for attr in user["Attributes"]}
    return {
        "email": attrs.get("email", ""),
        "name": attrs.get("name", ""),
        "enabled": user["Enabled"],
        "last_login": attrs.get("custom:last_login", ""),
    }


def list_pending_users() -> list[dict]:
    """Lista cadastros aguardando aprovação do admin: conta desabilitada
    (Enabled=False) que já confirmou a posse do e-mail (UserStatus=CONFIRMED).

    ListUsers só filtra 1 atributo por vez no server-side — filtra por
    status="Disabled" (atributo nativo "Enabled" do Cognito) e descarta em Python
    quem ainda está UNCONFIRMED (ainda não confirmou o e-mail; não deve aparecer
    para o admin, ver sign_up()/confirm_sign_up())."""
    response = _cognito_client().list_users(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Filter='status = "Disabled"',
    )
    return [_parse_user(user) for user in response["Users"] if user["UserStatus"] == "CONFIRMED"]


def list_active_users() -> list[dict]:
    """Lista usuários aprovados e habilitados (status Confirmed + Enabled=True).

    Filtra por status="Enabled" no server-side (não mais só por
    cognito:user_status) — sem isso, contas aguardando aprovação (Disabled +
    CONFIRMED) apareceriam aqui também, duplicando a linha do usuário no painel
    admin. Client-side ainda descarta UserStatus != CONFIRMED por defesa, embora
    não deva ocorrer no fluxo normal (uma conta Enabled=True nunca deveria estar
    UNCONFIRMED, já que sign_up() sempre desabilita)."""
    response = _cognito_client().list_users(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Filter='status = "Enabled"',
    )
    return [_parse_user(user) for user in response["Users"] if user["UserStatus"] == "CONFIRMED"]


def approve_signup(email: str) -> None:
    """Aprova um cadastro pendente, reabilitando a conta (AdminEnableUser).

    Não confirma mais a conta nem marca o e-mail como verificado — o próprio usuário
    já fez as duas coisas via o código de confirmação de cadastro (confirm_sign_up),
    pré-requisito para aparecer em list_pending_users()."""
    _cognito_client().admin_enable_user(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email
    )


def reject_signup(email: str) -> None:
    """Reprova um cadastro pendente, excluindo a conta por completo (decisão do
    projeto: sem histórico de reprovados, ver lightsail_ia.md)."""
    _cognito_client().admin_delete_user(UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email)


def revoke_access(email: str) -> None:
    """Revoga o acesso de um usuário já ativo, excluindo a conta por completo (mesma
    decisão do projeto usada em reject_signup: sem histórico de usuários revogados,
    ver lightsail_ia.md)."""
    _cognito_client().admin_delete_user(UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email)


def add_to_admins_group(email: str) -> None:
    """Adiciona o e-mail ao grupo "admins" do Cognito — usado pelo bootstrap manual do
    primeiro admin (ver lightsail_ia.md, não tem tela própria no painel)."""
    _cognito_client().admin_add_user_to_group(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email, GroupName="admins"
    )


def notify_new_signup(email: str, name: str) -> None:
    """Publica no tópico SNS de cadastro novo (infra/sns_topics.tf), para o admin saber
    que há alguém esperando aprovação sem precisar checar o painel periodicamente.
    Chamado por login.py só depois que o usuário confirma a posse do e-mail
    (confirm_sign_up bem-sucedido) — não mais logo após sign_up() — para o admin só
    ser avisado de cadastros que já provaram o e-mail."""
    client = boto3.client("sns", region_name=os.getenv("AWS_REGION", "sa-east-1"))
    client.publish(
        TopicArn=os.environ["SNS_NEW_SIGNUP_TOPIC_ARN"],
        Subject="FilmBot — cadastro novo pendente de aprovação",
        Message=f"{name} ({email}) acabou de se cadastrar no FilmBot e está aguardando aprovação.",
    )
