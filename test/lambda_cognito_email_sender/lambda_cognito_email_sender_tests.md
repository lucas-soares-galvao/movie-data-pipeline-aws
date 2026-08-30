# Testes — lambda_cognito_email_sender

## O que é testado

Testa a função `lambda_handler` em `app/lambda_cognito_email_sender/main.py` e as funções utilitárias em `app/lambda_cognito_email_sender/src/utils.py`. Testes unitários com estilo **pytest** (classes simples, `assert` nativo, `with patch(...)` como context manager). Nenhuma chamada real a KMS, Secrets Manager ou Gmail — tudo mockado via `unittest.mock`.

## Estrutura

```
test/lambda_cognito_email_sender/
├── conftest.py               # Placeholder de configuração (sem fixtures no momento)
├── requirements_tests.txt    # Dependências de teste
├── test_main.py              # Testes do lambda_handler
└── test_utils.py             # Testes das funções utilitárias
```

## Setup

A variável de ambiente `KMS_KEY_ARN` é definida via `os.environ.setdefault()` no início de `test_main.py`, antes do import de `main.py` (mesmo padrão de `test/lambda_api/test_main.py`).

## Casos de teste — `test_main.py`

### `TestLambdaHandler`

| Teste | O que verifica |
|---|---|
| `test_descriptografa_e_envia_email_para_sign_up` | `decrypt_code` é chamado com o código base64 do evento, `KMS_KEY_ARN` e o cliente KMS; `send_gmail_email` recebe o e-mail do usuário, assunto e corpo de confirmação de cadastro |
| `test_resend_code_usa_o_mesmo_texto_do_sign_up` | `triggerSource="CustomEmailSender_ResendCode"` gera o mesmo assunto/corpo do cadastro |
| `test_forgot_password_envia_texto_de_recuperacao` | `triggerSource="CustomEmailSender_ForgotPassword"` gera assunto/corpo de recuperação de senha |
| `test_trigger_source_nao_tratado_nao_envia_email` | `triggerSource` fora dos 3 fluxos usados pelo FilmBot (ex.: `Authentication`) não chama `send_gmail_email` |
| `test_nao_descriptografa_quando_evento_nao_traz_code` | Evento sem `request.code` não chama `decrypt_code` nem `send_gmail_email` |

## Casos de teste — `test_utils.py`

### `TestDecryptCode`

| Teste | O que verifica |
|---|---|
| `test_decifra_o_codigo_usando_o_keyring_da_chave_informada` | `EncryptionSDKClient` é criado com `CommitmentPolicy.REQUIRE_ENCRYPT_ALLOW_DECRYPT`; `decrypt()` recebe o ciphertext decodificado de base64 e o keyring; retorna o texto plano decodificado |
| `test_cria_o_keyring_com_a_chave_e_o_cliente_kms_informados` | `CreateAwsKmsKeyringInput` é montado com o `kms_key_id` e o `kms_client` recebidos |

### `TestBuildEmailContent`

| Teste | O que verifica |
|---|---|
| `test_sign_up_retorna_texto_de_confirmacao_de_cadastro` | `CustomEmailSender_SignUp` retorna assunto "Confirme seu e-mail — FilmBot" com o código no corpo |
| `test_resend_code_usa_o_mesmo_texto_do_sign_up` | `CustomEmailSender_ResendCode` retorna exatamente o mesmo (assunto, corpo) que `SignUp` |
| `test_forgot_password_retorna_texto_de_recuperacao_de_senha` | `CustomEmailSender_ForgotPassword` retorna assunto "Recuperação de senha — FilmBot" |
| `test_trigger_source_nao_tratado_retorna_none` | Os 5 `triggerSource` não usados pelo FilmBot (`Authentication`, `UpdateUserAttribute`, `VerifyUserAttribute`, `AdminCreateUser`, `AccountTakeOverNotification`) retornam `None` |

### `TestLoadGmailCredentials` / `TestSendGmailEmail`

Mesmos casos de `test/lightsail_ia/test_infrastructure.py` (`TestNotifyUserApproved`, credenciais do Gmail) — duplicados aqui de propósito, ver "Por que a lógica de Gmail é duplicada, não compartilhada" em `lambda_cognito_email_sender.md`.

| Teste | O que verifica |
|---|---|
| `test_busca_credenciais_do_secrets_manager` | Credenciais vêm do Secrets Manager quando `FILMBOT_SECRET_ARN` está configurado |
| `test_cai_para_fallback_de_env_vars_quando_secret_arn_nao_configurado` | Sem `FILMBOT_SECRET_ARN`, usa `GMAIL_SENDER_EMAIL`/`GMAIL_APP_PASSWORD` sem chamar boto3 |
| `test_cai_para_fallback_quando_secret_nao_tem_as_chaves_gmail` | Secret existe mas sem as chaves `gmail_*` — cai para o fallback de env vars |
| `test_retorna_none_quando_nenhuma_credencial_esta_configurada` | Sem nenhuma fonte de credencial, retorna `None` |
| `test_envia_email_com_sucesso` | `smtplib.SMTP_SSL` é chamado corretamente, mensagem montada com `Subject`/`From`/`To` corretos |
| `test_retorna_false_sem_chamar_smtp_quando_nenhuma_credencial_esta_configurada` | Sem credenciais, não chama SMTP e retorna `False` |
| `test_loga_erro_sem_propagar_quando_smtp_falha` | Falha de conexão SMTP é capturada, retorna `False` sem lançar |

## Como executar

```bash
# Apenas os testes da lambda_cognito_email_sender
pytest test/lambda_cognito_email_sender/ -v

# Com cobertura
pytest test/lambda_cognito_email_sender/ --cov=app/lambda_cognito_email_sender --cov-report=term-missing
```

## Cobertura mínima

**95%** — definido via `--cov-fail-under=95` no workflow de CI (`.github/workflows/01_test.yml`). O CI falha se a cobertura ficar abaixo desse limite.
