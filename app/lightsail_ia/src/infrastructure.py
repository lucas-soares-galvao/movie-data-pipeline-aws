"""infrastructure.py — bootstrap de processo e utilitários de rate limiting do FilmBot."""

import json
import logging
import math
import os
import smtplib
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import boto3
import streamlit as st
import watchtower
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


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
    """Cadastra um novo usuário no Cognito (SignUp) — fica Enabled=true (padrão) até
    confirmar o e-mail (ver confirm_sign_up).

    O primeiro código de confirmação de e-mail é enviado automaticamente como efeito
    colateral do próprio SignUp — o pool tem auto_verified_attributes=["email"] +
    verification_message_template configurados (infra/lightsail_ia.tf); diferente do
    reset de senha (request_password_reset), não existe uma chamada explícita de
    "enviar código" aqui.

    Não desabilita a conta aqui de propósito — testado empiricamente contra o Cognito
    real: ConfirmSignUp rejeita o código com CodeMismatchException (mensagem enganosa,
    não é o código que está errado) quando a conta já está Disabled. Desabilitar cedo
    demais quebra o próprio fluxo de confirmação; ver confirm_sign_up()."""
    _cognito_client().sign_up(
        ClientId=os.environ["COGNITO_APP_CLIENT_ID"],
        Username=email,
        Password=password,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "name", "Value": name},
        ],
    )


def confirm_sign_up(email: str, code: str) -> None:
    """Confirma a posse do e-mail do cadastro (ConfirmSignUp) e só então desabilita a
    conta (AdminDisableUser), até o admin aprovar em approve_signup().

    A ordem importa: ConfirmSignUp exige a conta Enabled=true pra aceitar o código
    (testado empiricamente — com Enabled=false ele rejeita qualquer código, mesmo o
    certo, com CodeMismatchException). Por isso sign_up() não desabilita mais a conta
    — só depois do ConfirmSignUp ter sucesso é que fica seguro desabilitar, sem quebrar
    a própria confirmação. UserStatus vira CONFIRMED e, por "email" estar em
    auto_verified_attributes (infra/lightsail_ia.tf), o Cognito marca
    email_verified=true sozinho nesse momento (comportamento padrão de auto-verified
    attribute ligado ao código de confirmação do SignUp).

    Exceptions relevantes do ConfirmSignUp: CodeMismatchException, ExpiredCodeException,
    LimitExceededException, TooManyFailedAttemptsException, AliasExistsException,
    UserNotFoundException (ver _signup_code_error_message em forms.py para o
    mapeamento de mensagem)."""
    client = _cognito_client()
    client.confirm_sign_up(
        ClientId=os.environ["COGNITO_APP_CLIENT_ID"],
        Username=email,
        ConfirmationCode=code,
    )
    client.admin_disable_user(UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email)


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
    para senha incorreta), para não colidir. A string exata foi confirmada empiricamente
    contra o Cognito real (AdminInitiateAuth numa conta Disabled); não é, ainda assim,
    um contrato documentado da API — se a AWS mudar o texto no futuro, o pior caso é
    essa branch nunca bater e o usuário ver "e-mail ou senha incorretos" em vez de
    "aguardando aprovação": degradação segura, não uma falha de segurança."""
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
    para a coluna "Último acesso" do painel admin. Chamado por forms.py logo após
    um authenticate() com retorno "ok"."""
    _cognito_client().admin_update_user_attributes(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Username=email,
        UserAttributes=[{"Name": "custom:last_login", "Value": datetime.now(timezone.utc).isoformat()}],
    )


def record_password_update(email: str) -> None:
    """Grava o timestamp (ISO 8601 UTC) da troca de senha bem-sucedida no atributo
    custom `custom:password_updated_at` (infra/lightsail_ia.tf), lido de volta por
    _parse_user() para a coluna "Atualizado em" do painel admin. Chamado por forms.py
    logo após um confirm_password_reset() bem-sucedido."""
    _cognito_client().admin_update_user_attributes(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Username=email,
        UserAttributes=[
            {"Name": "custom:password_updated_at", "Value": datetime.now(timezone.utc).isoformat()}
        ],
    )


def get_user_profile(email: str) -> dict:
    """Busca nome/e-mail atuais do usuário logado (ListUsers filtrado por e-mail, mesma
    chamada de get_user_status()) — usado por profile.py para pré-preencher a tela "Meu
    Perfil". Reaproveita _parse_user() (já usado pelo painel admin). Levanta IndexError
    se o e-mail não existir — não deveria acontecer para quem já está autenticado nesta
    sessão."""
    response = _cognito_client().list_users(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Filter=f'email = "{email}"',
    )
    return _parse_user(response["Users"][0])


def update_user_name(email: str, name: str) -> None:
    """Grava o nome novo no atributo padrão `name` (AdminUpdateUserAttributes) — chamado
    pela seção "Nome" da tela de perfil (profile.py). Mesmo padrão de record_login()/
    record_password_update(), nenhuma permissão IAM nova (AdminUpdateUserAttributes já
    concedida)."""
    _cognito_client().admin_update_user_attributes(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Username=email,
        UserAttributes=[{"Name": "name", "Value": name}],
    )


def change_password(email: str, current_password: str, new_password: str) -> str:
    """Troca a senha do usuário logado a partir do próprio perfil: reautentica com a
    senha atual (authenticate(), prova que quem está pedindo a troca ainda conhece a
    senha em vigor) e, só se válida, define a nova via AdminSetUserPassword
    (Permanent=True — o usuário já pode logar com ela imediatamente, sem o estado
    intermediário FORCE_CHANGE_PASSWORD).

    Retorna "ok" ou "invalid" (senha atual incorreta) — mesmo contrato de authenticate(),
    para o chamador (profile.py) tratar sem precisar distinguir uma exceção nova só para
    esse caso esperado."""
    status = authenticate(email, current_password)
    if status != "ok":
        return "invalid"
    _cognito_client().admin_set_user_password(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Username=email,
        Password=new_password,
        Permanent=True,
    )
    return "ok"


def apply_resumed_signup(email: str, password: str, name: str) -> None:
    """Grava a senha e o nome digitados na tela de confirmação de um cadastro retomado
    (e-mail que já existia como UNCONFIRMED, ver _start_signup_resume em forms.py) —
    só deve ser chamada depois que confirm_sign_up() já validou o código de confirmação,
    ou seja, depois de provar posse do e-mail. Chamar isso antes da confirmação seria uma
    brecha de account takeover (ver docstring de _start_signup_resume).

    Não reaproveita change_password(): ele reautentica via authenticate()
    (AdminInitiateAuth) antes de trocar a senha, mas nesse ponto do fluxo a conta acabou
    de ser desabilitada por confirm_sign_up() (aguardando aprovação do admin) e
    AdminInitiateAuth falharia numa conta Disabled. Aqui a posse do código de confirmação
    já é a prova de identidade necessária — mesmo racional de confirm_password_reset(),
    que troca a senha no mesmo passo em que valida o código, sem reautenticação extra."""
    client = _cognito_client()
    client.admin_set_user_password(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Username=email,
        Password=password,
        Permanent=True,
    )
    client.admin_update_user_attributes(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Username=email,
        UserAttributes=[{"Name": "name", "Value": name}],
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


def get_unconfirmed_signup_name(email: str) -> str:
    """Busca o nome gravado num cadastro ainda UNCONFIRMED (ListUsers filtrado por
    e-mail), pra pré-preencher o campo Nome na tela de confirmação de um cadastro
    retomado (ver _start_signup_resume em forms.py). Só deve ser chamada depois que
    get_user_status() já confirmou UNCONFIRMED para esse e-mail — levanta IndexError
    caso contrário."""
    response = _cognito_client().list_users(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Filter=f'email = "{email}"',
    )
    return _parse_user(response["Users"][0])["name"]


def request_password_reset(email: str) -> None:
    """Dispara o código de recuperação de senha (ForgotPassword) — o Cognito gera,
    envia e expira o código sozinho, usando o remetente nativo dele (sem SES). Só
    funciona se o e-mail já estiver marcado como verificado, o que acontece na
    confirmação do próprio cadastro (ver confirm_sign_up)."""
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
    """Extrai email/name/enabled/created_at/updated_at/last_login de um item retornado
    por list_users (Attributes vem como lista de {Name, Value}, não como dict).
    `created_at` vem de UserCreateDate, campo nativo do Cognito (sempre presente, sem
    depender de atributo custom). `updated_at` vem do atributo custom
    custom:password_updated_at, gravado só por record_password_update() no fluxo de
    troca de senha — não usa UserLastModifiedDate (nativo) de propósito, porque esse
    campo reflete qualquer alteração na conta, inclusive o próprio record_login() a
    cada login, o que o tornaria redundante com `last_login`. `updated_at`/`last_login`
    vêm vazios para quem nunca trocou a senha/nunca logou desde que os atributos custom
    existem (cadastros antigos, ou pendentes que nunca completaram o fluxo)."""
    attrs = {attr["Name"]: attr["Value"] for attr in user["Attributes"]}
    return {
        "email": attrs.get("email", ""),
        "name": attrs.get("name", "").strip(),
        "enabled": user["Enabled"],
        "created_at": user["UserCreateDate"].isoformat(),
        "updated_at": attrs.get("custom:password_updated_at", ""),
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
    admin. O filtro client-side por UserStatus == "CONFIRMED" aqui não é só defesa:
    um cadastro que ainda não confirmou o e-mail fica Enabled=True (padrão) +
    UNCONFIRMED durante essa janela curta (sign_up() não desabilita mais a conta,
    ver docstring de confirm_sign_up) — sem esse filtro, apareceria aqui como
    usuário ativo antes mesmo de confirmar o e-mail."""
    response = _cognito_client().list_users(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Filter='status = "Enabled"',
    )
    return [_parse_user(user) for user in response["Users"] if user["UserStatus"] == "CONFIRMED"]


def list_unconfirmed_users() -> list[dict]:
    """Lista cadastros que ainda não confirmaram a posse do e-mail (UserStatus=UNCONFIRMED).
    Ficam Enabled=true (sign_up() não desabilita mais a conta, ver confirm_sign_up()) e por
    isso não aparecem em list_pending_users() nem em list_active_users() — cadastros
    abandonados nesse estado ficavam invisíveis e sem trilha de limpeza no painel admin.

    Mesmo filtro server-side de list_active_users() (status="Enabled") — os dois estados
    (UNCONFIRMED e CONFIRMED ativo) compartilham Enabled=true, então reaproveitar o Filter
    já testado e invertendo a condição client-side evita introduzir uma sintaxe de Filter
    nova (ex.: cognito:user_status) não usada em nenhum outro lugar do projeto."""
    response = _cognito_client().list_users(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"],
        Filter='status = "Enabled"',
    )
    return [_parse_user(user) for user in response["Users"] if user["UserStatus"] == "UNCONFIRMED"]


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


# Mesmo domínio fixo de produção usado pelo Caddy (FILMBOT_DOMAIN em .env.caddy, ver
# .github/workflows/04_deploy_lightsail.yml) — hardcoded aqui porque o domínio não
# varia (só existe deploy em prod, ver workflow.md).
_FILMBOT_URL = "https://filmbot.lsgalvao.com.br"


def notify_new_signup(email: str, name: str) -> None:
    """Publica no tópico SNS de cadastro novo (infra/sns_topics.tf), para o admin saber
    que há alguém esperando aprovação sem precisar checar o painel periodicamente.
    Chamado por forms.py só depois que o usuário confirma a posse do e-mail
    (confirm_sign_up bem-sucedido) — não mais logo após sign_up() — para o admin só
    ser avisado de cadastros que já provaram o e-mail."""
    client = boto3.client("sns", region_name=os.getenv("AWS_REGION", "sa-east-1"))
    client.publish(
        TopicArn=os.environ["SNS_NEW_SIGNUP_TOPIC_ARN"],
        Subject="FilmBot — Cadastro Novo Pendente de Aprovação",
        Message=(
            f"{name} ({email}) acabou de se cadastrar no FilmBot e está aguardando aprovação. "
            f"Link: {_FILMBOT_URL}"
        ),
    )


def _load_gmail_credentials() -> tuple[str, str] | None:
    """Busca remetente + senha de app do Gmail para notify_user_approved: do
    FILMBOT_SECRET_ARN (chaves gmail_sender_email/gmail_app_password) em produção, ou
    das env vars GMAIL_SENDER_EMAIL/GMAIL_APP_PASSWORD como fallback de dev local —
    mesmo padrão de load_filmbot_password/agent.py::_load_llm_api_key. Retorna None se
    nenhuma das duas fontes tiver as duas credenciais."""
    secret_arn = os.getenv("FILMBOT_SECRET_ARN")
    if secret_arn:
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "sa-east-1"))
        response = client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response["SecretString"])
        sender_email = secret.get("gmail_sender_email")
        app_password = secret.get("gmail_app_password")
        if sender_email and app_password:
            return sender_email, app_password

    sender_email = os.getenv("GMAIL_SENDER_EMAIL")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    if sender_email and app_password:
        return sender_email, app_password
    return None


def _send_gmail_email(to_email: str, subject: str, body: str) -> bool:
    """Monta e envia (via Gmail/SMTP) um e-mail de notificação — reaproveitado por
    notify_user_approved/notify_user_rejected/notify_user_revoked. Retorna se o envio
    teve sucesso, pra admin.py poder informar o admin (ver admin_action_feedback).

    Uma falha aqui (credencial errada, Gmail fora do ar) só é reportada de volta pro
    retorno — nunca lançada — porque não pode derrubar a ação do Cognito que já
    aconteceu antes desta chamada."""
    credentials = _load_gmail_credentials()
    if credentials is None:
        logger.warning("Credenciais do Gmail não configuradas — e-mail não enviado para '%s'.", to_email)
        return False
    sender_email, app_password = credentials

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.send_message(message)
    except Exception as exc:  # noqa: BLE001 — falha ao notificar não deve afetar uma ação já concluída
        logger.error("Falha ao enviar e-mail para '%s': %s", to_email, exc)
        return False
    else:
        logger.info("E-mail enviado para '%s' (assunto: '%s').", to_email, subject)
        return True


def notify_user_approved(email: str, name: str) -> bool:
    """Envia (via Gmail/SMTP) o e-mail avisando o usuário que o cadastro foi aprovado e
    o acesso já está liberado. Chamado por admin.py logo após approve_signup(). Retorna
    se o envio teve sucesso."""
    return _send_gmail_email(
        email,
        "FilmBot — Cadastro Aprovado",
        f"Olá, {name}!\n\n"
        "Seu cadastro no FilmBot foi aprovado. Você já pode fazer login "
        f"em {_FILMBOT_URL} usando o e-mail {email} e a senha que você cadastrou.\n\n"
        "Até já,\nEquipe FilmBot",
    )


def notify_user_rejected(email: str, name: str) -> bool:
    """Envia (via Gmail/SMTP) o e-mail avisando o usuário que o cadastro não foi
    aprovado. Chamado por admin.py só quando o admin marca "Notificar por e-mail" no
    modal de confirmação de Reprovar — não é automático (ver lightsail_ia.md: notificar
    todo mundo sinalizaria pra estranhos/spam que o e-mail existe e foi rejeitado).
    Retorna se o envio teve sucesso."""
    return _send_gmail_email(
        email,
        "FilmBot — Cadastro Não Aprovado",
        f"Olá, {name}!\n\nSeu cadastro no FilmBot não foi aprovado.\n\nAté já,\nEquipe FilmBot",
    )


def notify_user_revoked(email: str, name: str) -> bool:
    """Envia (via Gmail/SMTP) o e-mail avisando o usuário que o acesso foi revogado.
    Chamado por admin.py só quando o admin marca "Notificar por e-mail" no modal de
    confirmação de Revogar. Retorna se o envio teve sucesso."""
    return _send_gmail_email(
        email,
        "FilmBot — Acesso Revogado",
        f"Olá, {name}!\n\nSeu acesso ao FilmBot foi revogado.\n\nAté já,\nEquipe FilmBot",
    )
