# lambda_cognito_email_sender — Envio Customizado do Código do Cognito

## O que é

Função Lambda acionada pelo trigger nativo `CustomEmailSender` do Cognito (`infra/lightsail_ia.tf`, bloco `lambda_config` do `aws_cognito_user_pool.filmbot`). Sempre que o Cognito precisaria enviar um código de verificação por e-mail (cadastro, reenvio de código, recuperação de senha), ele invoca esta Lambda em vez de enviar pelo remetente nativo dele — a Lambda descriptografa o código e o envia pelo Gmail.

## Por que existe

O remetente nativo do Cognito (usado quando o user pool não tem `email_configuration`) é um domínio compartilhado por milhares de outros User Pools de outras contas AWS, sem nenhum SPF/DKIM/DMARC controlado pelo projeto — o e-mail do código de verificação caía quase sempre em spam. A alternativa mais completa (Amazon SES com domínio próprio verificado) foi descartada por exigir acesso a DNS e possivelmente sair do sandbox do SES (production access request). Este módulo resolve o problema reaproveitando o envio via Gmail/SMTP que o projeto já usa para as notificações do admin (`app/lightsail_ia/src/infrastructure.py::notify_user_approved`/`notify_user_rejected`/`notify_user_revoked`) — e-mail que sai de verdade pelos servidores do Google, herdando o SPF/DKIM legítimo do domínio `gmail.com`.

O Cognito continua gerando e controlando o código internamente (mesma expiração, mesmo limite de tentativas, mesma proteção contra força bruta de sempre) — nada disso é reimplementado aqui. A única mudança é *quem entrega* o e-mail.

## Como funciona

1. O Cognito gera o código de verificação e o criptografa com a chave KMS configurada em `lambda_config.kms_key_id` (`aws_kms_key.cognito_email_sender`, `infra/kms.tf`), usando o [AWS Encryption SDK](https://docs.aws.amazon.com/encryption-sdk/latest/developer-guide/introduction.html).
2. O Cognito invoca esta Lambda com um evento contendo `triggerSource`, `request.code` (string base64 do código criptografado) e `request.userAttributes` (inclui `email`).
3. `main.lambda_handler` descriptografa o código via `decrypt_code()` (KMS keyring + AWS Encryption SDK) quando `request.code` está presente.
4. `build_email_content()` decide o assunto/corpo do e-mail a partir do `triggerSource`:
   - `CustomEmailSender_SignUp` e `CustomEmailSender_ResendCode` — mesmo texto de confirmação de cadastro que antes vivia em `verification_message_template` (`infra/lightsail_ia.tf`).
   - `CustomEmailSender_ForgotPassword` — texto de recuperação de senha.
   - Qualquer outro `triggerSource` (`Authentication`, `UpdateUserAttribute`, `VerifyUserAttribute`, `AdminCreateUser`, `AccountTakeOverNotification`) — nenhum desses corresponde a um fluxo usado pelo FilmBot hoje (sem MFA por e-mail, sem alteração de e-mail própria, sem `AdminCreateUser`, sem detecção de risco configurada). `build_email_content` retorna `None` e o handler só loga, sem enviar nada — para não quebrar caso o Cognito dispare um desses eventos por engano ou numa configuração futura.
5. `send_gmail_email()` monta e envia o e-mail via `smtplib.SMTP_SSL("smtp.gmail.com", 465)`, autenticando com a mesma conta Gmail (`gmail_sender_email`/`gmail_app_password` no Secrets Manager) já usada pelas notificações do admin em `lightsail_ia`.

### Por que a lógica de Gmail é duplicada, não compartilhada

`app/lightsail_ia/src/infrastructure.py` já tem `_load_gmail_credentials`/`_send_gmail_email`, praticamente idênticas às daqui. Não foram movidas para `shared_utils` porque o deploy do `lightsail_ia` (`.github/workflows/04_deploy_lightsail.yml`) faz um `git clone` do repositório inteiro e roda a partir de `app/lightsail_ia/` sem nenhum passo de empacotamento — diferente de Lambda/Glue, que sempre embutem `shared_utils` no `.zip`/`.whl` via `build_lambda_package.py`/`build_glue_wheel.py`. Importar `shared_utils` em `lightsail_ia` exigiria manipular `sys.path`/`PYTHONPATH` na instância Lightsail em produção — risco desnecessário para ~20 linhas de código. A duplicação aqui é deliberada.

### Tratamento de erros

Nenhuma exceção de envio propaga para o Cognito — `send_gmail_email` captura qualquer falha (credencial errada, Gmail fora do ar) e retorna `False`, só logando o erro. O Cognito não espera nenhum retorno específico deste trigger (ver [doc oficial](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-custom-email-sender.html)) — lançar aqui só faria a invocação da Lambda aparecer como erro no CloudWatch, sem nenhum benefício para o usuário (o Cognito já processou o código internamente antes de chamar este trigger).

## Entradas e saídas

| | Descrição |
|---|---|
| **Entrada** | Evento do Cognito (`type=customEmailSenderRequestV1`): `triggerSource`, `request.code` (base64, criptografado), `request.userAttributes` (inclui `email`) |
| **Leitura** | AWS KMS (`Decrypt`, via AWS Encryption SDK), Secrets Manager (`gmail_sender_email`/`gmail_app_password`) |
| **Escrita** | Nenhuma — só efeito colateral de rede (envio SMTP) |
| **Aciona** | Nenhum outro serviço — ponta final do fluxo |

## Funções principais (`src/utils.py`)

| Função | Responsabilidade |
|---|---|
| `decrypt_code(...)` | Descriptografa `request.code` via AWS Encryption SDK + KMS keyring |
| `build_email_content(...)` | Decide assunto/corpo do e-mail a partir do `triggerSource`, ou `None` se não tratado |
| `load_gmail_credentials()` | Busca remetente/senha de app do Gmail (Secrets Manager, com fallback de env vars para dev local) |
| `send_gmail_email(...)` | Monta e envia o e-mail via `smtplib.SMTP_SSL` |

## Tecnologias

- **AWS Encryption SDK** (`aws-encryption-sdk[MPL]`) — descriptografia do código gerado pelo Cognito
- **AWS KMS** — chave simétrica dedicada (`infra/kms.tf`), usada pelo Cognito para criptografar e por esta Lambda para descriptografar
- **boto3** — clientes KMS e Secrets Manager
- **smtplib** (biblioteca padrão) — envio via Gmail/SMTP
