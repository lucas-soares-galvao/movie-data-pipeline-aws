# Skill: Estrutura do Projeto proj-eng-dados-filmes-aws

Você está trabalhando no projeto **proj-eng-dados-filmes-aws**. Esta skill descreve a organização de pastas, convenções e como cada parte se conecta.

---

## Árvore de Diretórios (resumida)

```
proj-eng-dados-filmes-aws/
├── .github/
│   └── workflows/
│       ├── 00_pipeline.yml        # Pipeline principal CI/CD (orquestrador)
│       ├── 01_test.yml            # Workflow reutilizável: testes + quality gates
│       ├── 02_terraform.yml       # Workflow reutilizável: infra Terraform
│       ├── 03_pr_auto.yml         # Workflow reutilizável: criação automática de PR
│       ├── 04_deploy_lightsail.yml # Deploy do app configurado via SSH no Lightsail
│       └── 05_backfill.yml        # Backfill manual sob demanda (workflow_dispatch, ambiente por branch)
├── app/
│   ├── lambda_api/
│   │   ├── main.py                # Handler da Lambda (entry point)
│   │   ├── requirements.txt
│   │   ├── lambda_api.md          # Documentação do módulo
│   │   └── src/utils.py           # Lógica de negócio: TMDB fetch, S3, Glue trigger
│   ├── glue_etl/
│   │   ├── main.py                # Entry point do Glue ETL
│   │   ├── requirements.txt
│   │   ├── glue_etl.md            # Documentação do módulo
│   │   └── src/utils.py           # get_parameters_glue, read_from_sor, write_parquet_to_sot, derive_canonical_name
│   ├── glue_data_quality/
│   │   ├── main.py                # Entry point do Glue DQ
│   │   ├── requirements.txt
│   │   ├── glue_data_quality.md   # Documentação do módulo
│   │   └── src/
│   │       ├── utils.py           # get_parameters_glue, get_ruleset, read_table_from_catalog, evaluate_data_quality, write_results_to_s3, notify_failed_outcomes
│   │       └── rulesets_dq.py     # Dict de rulesets DQDL por nome de tabela
│   ├── glue_details/
│   │   ├── main.py                # Entry point do Glue Details
│   │   ├── requirements.txt
│   │   ├── glue_details.md        # Documentação do módulo
│   │   └── src/utils.py           # Busca detalhes complementares (runtime, temporadas, streaming)
│   ├── glue_agg/
│   │   ├── main.py                # Entry point do Glue AGG
│   │   ├── requirements.txt
│   │   ├── glue_agg.md            # Documentação do módulo
│   │   └── src/utils.py           # Une filmes+séries via Athena SQL (CTEs + DENSE_RANK), escreve SPEC
│   ├── lightsail_ia/
│   │   ├── __init__.py
│   │   ├── agent.py               # Agente de recomendação: extrai filtros → Athena → formata
│   │   ├── app.py                 # Interface Streamlit (FilmBot)
│   │   ├── componentes.py         # Helpers de renderização HTML (CSS, cards, grid, rodapé)
│   │   ├── requirements.txt       # streamlit, litellm, boto3, python-dotenv
│   │   ├── lightsail_ia.md        # Documentação do módulo
│   │   ├── .env.example           # Exemplo de variáveis de ambiente
│   │   ├── .streamlit/secrets.toml.example  # Exemplo de config Streamlit
│   │   ├── static/
│   │   │   ├── login.css          # Estilos da tela de login
│   │   │   └── principal.css      # Estilos da página principal
│   │   └── deploy/setup.sh        # Configura systemd service no Lightsail
│   ├── lambda_lightsail_scheduler/
│   │   ├── main.py                # Handler Lambda para ligar/desligar instância Lightsail
│   │   ├── requirements.txt
│   │   └── lambda_lightsail_scheduler.md  # Documentação do módulo compartilhado
│       └── shared_utils/
│           ├── __init__.py
│           ├── api_client.py          # API client genérico com retry/backoff e Secrets Manager
│           ├── glue_helpers.py        # Utilitários compartilhados de jobs Glue (getResolvedOptions, logging)
│           ├── traducao.py            # Tradução inglês → português via Google Translate
│           └── triggers.py            # Disparo genérico de Glue jobs
├── infra/
│   ├── envs/
│   │   ├── dev/terraform.tfvars   # Variáveis do ambiente dev (account_id, secret ARN)
│   │   └── prod/terraform.tfvars  # Variáveis do ambiente prod (account_id, secret ARN)
│   ├── config/
│   │   ├── destroy_config.json    # Flag de destroy por ambiente: {"dev": false, "prod": false}
│   │   ├── project.json           # Fonte única de nomes/identidade do projeto (prefixo, role/policy CI/CD, wheel, app Lightsail) — lido pelo Terraform (jsondecode) e pelos workflows (jq)
│   │   └── export_env_local.sh    # Exporta variáveis de ambiente locais (usado pelo FilmBot)
│   ├── docs/
│   │   ├── overview.md            # Visão geral, ambientes, CI/CD, como aplicar
│   │   ├── recursos.md            # S3, Lambda, Glue Jobs, Glue Catalog, Lightsail
│   │   ├── pipeline.md            # EventBridge, Step Functions, SNS, CloudWatch
│   │   └── iam.md                 # IAM roles/policies, IAM CI/CD
│   ├── scripts/
│   │   ├── build_lambda_package.py
│   │   └── build_glue_wheel.py
│   ├── provider.tf                # Provider AWS (sa-east-1) + backend S3 dinâmico
│   ├── variables.tf                # Todas as variáveis Terraform
│   ├── locals.tf                   # Nomes de recursos sufixados por env, templates de alarme
│   ├── data.tf                     # Data sources (ex.: AWS account id, região)
│   ├── s3.tf                       # Buckets SOR, SOT, SPEC, DQ, AUX, TEMP
│   ├── iam_roles.tf                # Roles para Lambda e Glue
│   ├── iam_policies.tf             # Policies com privilégio mínimo
│   ├── iam_cicd.tf                 # 6 policies least-privilege da role GitHub Actions + sync
│   ├── lambda_api.tf               # Função Lambda + package zip
│   ├── glue_etl.tf                 # Glue Job ETL + upload de scripts no S3
│   ├── glue_details.tf             # Glue Job Details + upload de scripts no S3
│   ├── glue_agg.tf                 # Glue Job AGG + upload de scripts no S3
│   ├── glue_data_quality.tf        # Glue Job Data Quality + upload de scripts
│   ├── glue_catalog.tf             # Database e tabelas no Glue Catalog
│   ├── lightsail_ia.tf             # Instância Lightsail + IAM user filmbot-agent
│   ├── lightsail_scheduler.tf      # Lambda + EventBridge para ligar/desligar o Lightsail (custo)
│   ├── eventbridge.tf              # Regras EventBridge (semanal, mensal, anual)
│   ├── sns_topics.tf               # Tópicos SNS + subscrições de e-mail
│   ├── cloudwatch_alarms.tf        # Alarmes Lambda e EventBridge
│   ├── cloudwatch_glue_alarms.tf   # Alarmes Glue ETL e Data Quality
│   └──cloudwatch_logs.tf          # Log groups de cada serviço
├── scripts/
│   ├── backfill_shared.py         # Código comum aos scripts de backfill (env vars, logging, checkpoint em S3, retry)
│   ├── backfill_traducao.py       # Adiciona title_pt/overview_pt a dados históricos no S3 SOT
│   ├── backfill_historico.py      # Popula tabelas discover de 2000 até o ano atual via Lambda
│   └── backfill_data_quality.py   # Aciona o Glue Data Quality para tabelas de 2000 até o ano atual
└── test/
    ├── conftest.py                 # Fixtures globais
    ├── lambda_api/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── lambda_api_tests.md
    │   ├── test_main.py
    │   └── test_utils.py
    ├── glue_etl/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── glue_etl_tests.md
    │   ├── test_main.py
    │   └── test_utils.py
    ├── glue_data_quality/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── glue_data_quality_tests.md
    │   ├── test_main.py
    │   ├── test_rulesets_dq.py
    │   └── test_utils.py
    ├── glue_details/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── glue_details_tests.md
    │   ├── test_main.py
    │   └── test_utils.py
    ├── glue_agg/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── glue_agg_tests.md
    │   ├── test_main.py
    │   └── test_utils.py
    ├── lightsail_ia/
    │   ├── __init__.py
    │   ├── conftest.py             # Setup de env vars (não tem fixtures)
    │   ├── requirements_tests.txt
    │   ├── lightsail_tests.md
    │   └── test_agent.py           # Testes do agente de recomendação
    ├── lambda_lightsail_scheduler/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── lambda_lightsail_scheduler_tests.md
    │   └── test_main.py
    └── shared_src/
        ├── __init__.py
        ├── conftest.py
        ├── requirements_tests.txt
        ├── shared_src_tests.md
        ├── test_api_client.py
        ├── test_glue_helpers.py
        ├── test_traducao.py
        └── test_triggers.py
```

---

## GitHub Actions — Workflows

### `00_pipeline.yml` — Orquestrador principal

**Gatilhos:** push em `feature/*`, `develop`, `main` e `workflow_dispatch` (manual com input de ambiente).

**Fluxo de jobs:**

```
push em feature/*  →  test  →  auto-pr-feature (feature/* → develop)
push em develop    →  terraform (dev)  →  auto-pr-environment (develop → main)
push em main       →  terraform (prod)  →  deploy-lightsail (prod)
workflow_dispatch  →  terraform (env escolhido)  →  deploy-lightsail (apenas se prod)
```

**Secrets usados por ambiente (job `terraform`):**
| Secret | dev | prod |
|--------|-----|------|
| `AWS_ASSUME_ROLE_ARN` | `_DEV` | `_PROD` |
| `AWS_STATEFILE_S3_BUCKET` | `_DEV` | `_PROD` |
| `AWS_LOCK_DYNAMODB_TABLE` | `_DEV` | `_PROD` |
| `AWS_FILMBOT_SECRET_ARN` | `_DEV` | `_PROD` |

**Secrets sem sufixo de ambiente (compartilhados):** `NOTIFICATION_EMAIL` (e-mails de alerta da infra), `INFRACOST_API_KEY` (estimativa de custo no PR).

---

### `01_test.yml` — Quality Gates (reutilizável)

Chamado por `00_pipeline.yml` apenas em branches `feature/*`. Roda em `ubuntu-latest`.

**Etapas:**
1. Checkout do código
2. Setup Python 3.12 (com cache de pip)
3. Instala `pytest`, `pytest-cov`, `ruff`, `mypy`, `bandit`, `safety`
4. Instala `test/**/requirements_tests.txt` e `app/*/requirements.txt`
5. Configura `PYTHONPATH=$GITHUB_WORKSPACE`
6. **Ruff** — linting de `app/` e `test/`
7. **mypy** — type check de `app/` (informativo, não bloqueia)
8. **Bandit** — scan de segurança em `app/` (informativo)
9. **Safety** — vulnerabilidades em dependências (informativo)
10. **pytest** — testes com cobertura; **quality gate: ≥ 80% de cobertura** (`--cov-fail-under=80`, bloqueia se falhar)

---

### `02_terraform.yml` — Deploy de Infraestrutura (reutilizável)

**Inputs:** `environment` (dev | prod)  
**Secrets:** `aws-assume-role-arn`, `aws-statefile-s3-bucket`, `aws-lock-dynamodb-table`

**Etapas:**
1. Checkout + leitura de `infra/config/project.json` (nome do wheel compartilhado, prefixo/nome da role e policies de CI/CD, key do state file) via `jq`
2. Setup Terraform 1.8.3
3. Autenticação AWS via **OIDC** (sem Access Keys fixas)
4. Build dos pacotes Lambda (`infra/scripts/build_lambda_package.py`) e wheels do Glue (ETL, Agg, Details, Shared) — falha se algum artefato sair vazio
6. Lê `infra/config/destroy_config.json` para decidir destroy ou apply
7. `terraform init` com backend S3 dinâmico (bucket + key + região + DynamoDB lock)
8. `terraform validate`
9. **TFLint** — boas práticas Terraform (informativo)
10. **terraform fmt -check** (informativo)
11. **Checkov** — security/compliance scan (informativo)
12. Injeta o e-mail de notificação (`notification-email`) no `.tfvars`
13. **Bootstrap das IAM policies do CI/CD** (se não for destroy) — `terraform apply -target` nas 6 policies/attachments, depois faz polling em `aws iam list-attached-role-policies` (a cada 5s, timeout 60s) até confirmar que todas estão attachadas
14. Se `destroy_config[env] == true` → `terraform destroy`
15. Se não → `terraform plan -out=<env>.plan` → Infracost (setup, breakdown no Job Summary, comentário no PR se o evento for `pull_request`) → `terraform apply <env>.plan`

**Isolamento entre ambientes:** buckets S3 de state separados por ambiente (sem workspaces Terraform).

---

### `03_pr_auto.yml` — Auto Pull Request (reutilizável)

**Input:** `branch_name`

**Lógica de promoção:**
- `feature/*` → abre/atualiza PR para `develop`
- `develop` → abre/atualiza PR para `main`

Valida `terraform validate` (sem backend) antes de criar o PR.

---

### `04_deploy_lightsail.yml` — Deploy do App Configurado (reutilizável)

**Inputs:** `environment` (dev | prod)  
**Secrets:** `aws-assume-role-arn`, `aws-statefile-s3-bucket`, `aws-lock-dynamodb-table`

**Etapas:**
1. Checkout + leitura de `infra/config/project.json` (`app_name`, `app_display_name`, `app_folder`, `statefile_key`) via `jq`
2. Setup Terraform 1.8.3 (wrapper desabilitado para ler outputs raw)
3. Autenticação AWS via OIDC
4. `terraform init` e leitura de outputs: `lightsail_public_ip`, `lightsail_instance_name`, `lightsail_private_key`, `lightsail_agent_access_key_id`, `lightsail_agent_secret_access_key`, `lightsail_cloudwatch_log_group`, `lightsail_filmbot_secret_arn`, `lightsail_athena_s3_output`, `lightsail_glue_database`, `lightsail_spec_table` (credenciais mascaradas com `::add-mask::`)
5. Verifica o estado da instância via `aws lightsail get-instance` — pula o deploy com warning se não estiver `running`
6. **SSH readiness check:** `ssh-keyscan` com 30 tentativas × 10s (max 5 min). Falha explicitamente se SSH não estiver disponível ao fim das tentativas
7. Cria `/opt/<app_name>/app/<app_folder>/.env` diretamente no destino via `printf | ssh | tee` (evita escrita em `/tmp` world-readable), contendo credenciais AWS, `FILMBOT_SECRET_ARN` e `ATHENA_S3_OUTPUT`/`GLUE_DATABASE`/`SPEC_TABLE`/`CLOUDWATCH_LOG_GROUP` — todos lidos direto dos outputs do Terraform (não hardcoded no workflow)
8. Deploy da aplicação via SSH: `git clone` (primeiro deploy, URL derivada de `${{ github.repository }}`) ou `git pull` (atualizações), instala dependências, copia o service `<app_name>.service` + `caddy.service` e reinicia via `systemd`. `app_name`/`app_folder` são passados para dentro do heredoc SSH como variáveis de ambiente (mesmo padrão já usado para `BRANCH`)
9. Health check via `curl` no IP público

**Mapeamento de branch por ambiente:** `dev → develop`, `prod → main`

Por padrão (`infra/config/project.json`), `app_name=filmbot`, `app_folder=lightsail_ia`, `app_display_name=FilmBot` — trocar esses valores redireciona o deploy para outro app, mas os recursos AWS (IAM user, instância Lightsail) continuam nomeados a partir de `filmbot` hardcoded no lado Terraform (fora de escopo da genericização atual).

---

### `05_backfill.yml` — Backfill Manual

**Trigger:** `workflow_dispatch` apenas (independente do `00_pipeline.yml`). O ambiente (dev/prod) é resolvido **automaticamente pelo branch** selecionado em "Use workflow from": `main` → prod, `develop` → dev, qualquer outro branch falha o workflow antes de configurar credenciais AWS (step "Resolver ambiente a partir do branch").

**Inputs:** `table_group` (choice: discover | referencias | detalhes_e_providers | data_quality | traducao), `start_year` (default 2000), `end_year` (opcional)

**Mapeamento `table_group` → script:** `discover` → `backfill_historico.py`, `referencias` → `backfill_referencias.py`, `detalhes_e_providers` → `backfill_enriquecimento.py`, `data_quality` → `backfill_data_quality.py`, `traducao` → `backfill_traducao.py`

**Etapas:** Checkout → resolve ambiente pelo branch → lê `infra/config/project.json` (`project_prefix`, step "Ler configuração do projeto") → autenticação OIDC com `AWS_ASSUME_ROLE_ARN_DEV` ou `AWS_ASSUME_ROLE_ARN_PROD` conforme o ambiente resolvido (sessão padrão de 1h) → Setup Python 3.12 → instala `boto3` (+ `scripts/requirements_backfill.txt` só para `traducao`) → executa o script correspondente dentro de um loop de retry (até 10 tentativas). `timeout-minutes: 360`.

**Retomada automática (ExpiredTokenException):** os 4 scripts que iteram por ano (`discover`, `detalhes_e_providers`, `data_quality`, `traducao` — não `referencias`) gravam um checkpoint em `s3://{S3_BUCKET_TEMP}/tmdb/backfill_checkpoints/{TABLE_GROUP}.json` (`scripts/backfill_shared.py`) a cada unidade concluída, e saem com exit code 75 especificamente quando a credencial AWS expira no meio da execução. O step "Executar backfill" reconhece esse código: reassume a role via `aws sts assume-role-with-web-identity` inline (usando o token OIDC do job, `ACTIONS_ID_TOKEN_REQUEST_URL`/`ACTIONS_ID_TOKEN_REQUEST_TOKEN`, já que `permissions: id-token: write` está habilitado), obtém uma nova sessão de 1h e roda o script de novo — que retoma do checkpoint em vez de recomeçar do `start_year`. Qualquer outro erro (não relacionado a token) falha o job normalmente, sem retry. `backfill_traducao.py` usa adicionalmente `S3_BUCKET_SOT` para ler/escrever os parquets reais, separado do checkpoint.

Os nomes de recursos (`GLUE_*_JOB_NAME`, `*_DATABASE_*`, `TABLE_*`) são montados dinamicamente como `<project_prefix>-...-<ambiente>` / `<prefixo>_..._<ambiente>`, usando o prefixo lido de `infra/config/project.json` e o ambiente resolvido pelo branch — nenhum nome fica hardcoded no workflow (exceto `S3_BUCKET_SOT`/`S3_BUCKET_TEMP`, que usam o prefixo de bucket `lsg`, não o prefixo do projeto).

---

## Infra — Terraform

### Ambientes e Isolamento (AWS Organizations)

| Ambiente | AWS Account ID | Branch Git |
|----------|---------------|------------|
| `dev`    | `<AWS_ACCOUNT_ID_DEV>` | `develop` |
| `prod`   | `<AWS_ACCOUNT_ID_PROD>` | `main` |

Cada ambiente tem sua própria conta AWS (via AWS Organizations). O Terraform usa a role assumida via OIDC para acessar a conta correta. O state é separado por bucket S3 diferente por ambiente.

### Convenção de Nomes de Recursos

Todos os recursos são sufixados com o ambiente via `locals.tf`:
```
locals.envs.glue_etl_job_name  = "glue-etl-dev"       / "glue-etl-prod"
locals.envs.lambda_api_name    = "lambda-api-dev"      / "lambda-api-prod"
locals.envs.s3_bucket_sor      = "lsg-sa-east-1-bucket-sor-dev" / "...-prod"
```

### Arquivos `.tf` por responsabilidade

| Arquivo | O que cria |
|---------|-----------|
| `provider.tf` | Provider AWS (sa-east-1) + backend S3 dinâmico |
| `variables.tf` | Todas as variáveis Terraform |
| `locals.tf` | Nomes de recursos sufixados por env, templates de alarme |
| `data.tf` | Data sources (ex.: AWS account id, região) |
| `s3.tf` | 6 buckets: SOR, SOT, SPEC, DQ, AUX (código), TEMP (Athena) |
| `iam_roles.tf` | Role para Lambda, Role para Glue |
| `iam_policies.tf` | Policies de mínimo privilégio por serviço |
| `iam_cicd.tf` | 6 policies least-privilege da role GitHub Actions (nome/prefixo lidos de `infra/config/project.json`, default `lsg-github-actions-{env}`) + `terraform_data` de sincronização |
| `lambda_api.tf` | Lambda function + zip do pacote Python |
| `glue_etl.tf` | Glue Job ETL + upload de scripts/dependências no S3 AUX |
| `glue_details.tf` | Glue Job Details + upload de scripts no S3 AUX |
| `glue_agg.tf` | Glue Job AGG + upload de scripts no S3 AUX |
| `glue_data_quality.tf` | Glue Job DQ + upload de scripts no S3 AUX |
| `glue_catalog.tf` | Databases e tabelas no Glue Catalog |
| `lightsail_ia.tf` | Instância Lightsail + IAM user filmbot-agent |
| `lightsail_scheduler.tf` | Lambda + EventBridge para ligar/desligar o Lightsail (custo) |
| `eventbridge.tf` | Regras de schedule EventBridge (semanal, mensal, anual) → Lambda e Step Functions |
| `step_functions.tf` | State Machine de backfill histórico anual |
| `sqs.tf` | Fila SQS dead-letter para EventBridge |
| `shared_src.tf` | Build e upload do wheel compartilhado para S3 AUX |
| `sns_topics.tf` | Tópicos SNS + subscrições de e-mail para alertas |
| `cloudwatch_alarms.tf` | Alarmes Lambda e EventBridge (falha/sucesso) |
| `cloudwatch_glue_alarms.tf` | Alarmes Glue ETL e Glue DQ (falha/sucesso) |
| `cloudwatch_logs.tf` | Log groups de cada serviço |

### Controle de Destroy

Para destruir a infra de um ambiente, edite `infra/config/destroy_config.json`:
```json
{ "dev": true, "prod": false }
```
O pipeline detecta essa flag e executa `terraform destroy` automaticamente.

---

## App — Código Python

### Estrutura padrão de cada módulo

```
app/<modulo>/
├── main.py             # Entry point (handler Lambda ou __main__ Glue)
├── requirements.txt    # Dependências de produção
└── src/
    ├── __init__.py
    └── utils.py        # Toda a lógica de negócio (funções puras/testáveis)
```

**Regra:** a lógica fica em `src/utils.py`; o `main.py` apenas resolve args e delega.

### Dependências por módulo

| Módulo | Deps principais |
|--------|----------------|
| `lambda_api` | `boto3`, `requests` |
| `glue_etl` | `awswrangler`, `boto3`, `pandas`, `awsglue` (Glue runtime) |
| `glue_data_quality` | `awswrangler`, `awsgluedq`, `pyspark`, `awsglue` (Glue runtime) |
| `glue_details` | `awswrangler`, `boto3`, `pandas`, `requests`, `awsglue` (Glue runtime) |
| `glue_agg` | `awswrangler`, `boto3`, `pandas`, `awsglue` (Glue runtime) |
| `lightsail_ia` | `streamlit`, `litellm`, `boto3`, `python-dotenv` |
| `shared_src` | `boto3`, `requests`, `deep-translator` |
| `lambda_lightsail_scheduler` | `boto3` |

---

## Test — Testes

### Configuração (`pytest.ini`)

```ini
[pytest]
testpaths = test
pythonpath = . app/lambda_api
python_files = test_*.py
```

### Estrutura espelhada

`test/` espelha `app/`: cada módulo tem seu próprio `conftest.py`, `requirements_tests.txt` e arquivos `test_*.py`.

### Convenções

- Testes escritos com **unittest** e executados pelo **pytest**
- Mocks via `unittest.mock` (patch de `boto3`, `requests`, etc.)
- `conftest.py` por módulo para fixtures compartilhadas
- `test/conftest.py` raiz para fixtures globais
- `requirements_tests.txt` separado por módulo — instala apenas o necessário para testar aquele serviço

### Quality Gate

O pipeline bloqueia se a cobertura de `app/` for **menor que 80%** (definido no workflow `.github/workflows/01_test.yml`, não no `pytest.ini`).  
Rodar localmente: `pytest --cov=app --cov-report=term-missing --cov-fail-under=80`
