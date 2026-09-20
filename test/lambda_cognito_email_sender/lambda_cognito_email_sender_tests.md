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
| `test_descriptografa_e_envia_email_para_sign_up` | `decrypt_code` é chamado com o código base64 do evento, `KMS_KEY_ARN` e o cliente KMS; o cliente KMS é criado com `config=` (timeout explícito); `send_gmail_email` recebe o e-mail do usuário, assunto e corpo de confirmação de cadastro |
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

### `TestGmailHelpersReexport`

`load_gmail_credentials`/`send_gmail_email` vivem em `shared_utils/gmail_helpers.py`
(ver `test/shared_src/test_gmail_helpers.py` para os casos de borda) — `src/utils.py`
só reexporta as duas. Aqui só confirma que a reexportação funciona (chamando por
`src.utils`, não comparando por identidade — ver comentário no teste sobre o reload de
`shared_utils.*` entre suites em `test/conftest.py`).

| Teste | O que verifica |
|---|---|
| `test_send_gmail_email_reexportado_funciona_sem_credenciais` | `src.utils.send_gmail_email` chamado sem nenhuma credencial configurada retorna `False` |
| `test_load_gmail_credentials_reexportado_funciona_com_env_vars` | `src.utils.load_gmail_credentials` chamado com `GMAIL_SENDER_EMAIL`/`GMAIL_APP_PASSWORD` retorna a tupla esperada |

## Como executar

```bash
# Apenas os testes da lambda_cognito_email_sender
pytest test/lambda_cognito_email_sender/ -v

# Com cobertura
pytest test/lambda_cognito_email_sender/ --cov=app/lambda_cognito_email_sender --cov-report=term-missing
```

## Cobertura mínima

**100%** — definido via `--cov-fail-under=100` no workflow de CI (`.github/workflows/test.yml`). O CI falha se a cobertura ficar abaixo desse limite.
