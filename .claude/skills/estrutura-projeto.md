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
│       └── 04_deploy_lightsail.yml # Deploy do FilmBot via SSH no Lightsail
├── app/
│   ├── lambda_api/
│   │   ├── main.py                # Handler da Lambda (entry point)
│   │   ├── requirements.txt
│   │   └── src/utils.py           # Lógica de negócio: TMDB fetch, S3, Glue trigger
│   ├── glue_etl/
│   │   ├── main.py                # Entry point do Glue ETL
│   │   ├── requirements.txt
│   │   └── src/utils.py           # process_tmdb, run_etl, call_glue_data_quality
│   ├── glue_data_quality/
│   │   ├── main.py                # Entry point do Glue DQ
│   │   ├── requirements.txt
│   │   └── src/
│   │       ├── utils.py           # parse_args, build_ruleset, run_data_quality, write_results
│   │       └── rulesets_dq.py     # Dict de rulesets DQDL por nome de tabela
│   ├── glue_details/
│   │   ├── main.py                # Entry point do Glue Details
│   │   ├── requirements.txt
│   │   └── src/utils.py           # Busca detalhes complementares (runtime, temporadas, streaming)
│   ├── glue_agg/
│   │   ├── main.py                # Entry point do Glue AGG
│   │   ├── requirements.txt
│   │   └── src/utils.py           # Une filmes+séries, traduz título/sinopse, escreve SPEC
│   ├── lightsail_ia/
│   │   ├── agent.py               # Agente de recomendação: extrai filtros → Athena → formata
│   │   ├── app.py                 # Interface Streamlit (FilmBot)
│   │   ├── requirements.txt       # streamlit, litellm, boto3, python-dotenv
│   │   └── deploy/setup.sh        # Configura systemd service no Lightsail
│   └── lambda_lightsail_scheduler/
│       ├── main.py                # Handler Lambda para ligar/desligar instância Lightsail
│       └── requirements.txt
├── infra/
│   ├── envs/
│   │   ├── dev/terraform.tfvars   # Variáveis do ambiente dev (account_id, secret ARN)
│   │   └── prod/terraform.tfvars  # Variáveis do ambiente prod (account_id, secret ARN)
│   ├── scripts/
│   │   ├── build_lambda_package.py
│   │   └── build_glue_wheel.py
│   ├── provider.tf                # Provider AWS (sa-east-1) + backend S3 dinâmico
│   ├── variables.tf               # Todas as variáveis Terraform
│   ├── locals.tf                  # Nomes de recursos sufixados por env, templates de alarme
│   ├── s3.tf                      # Buckets SOR, SOT, SPEC, DQ, AUX, TEMP
│   ├── iam_roles.tf               # Roles para Lambda e Glue
│   ├── iam_policies.tf            # Policies com privilégio mínimo
│   ├── lambda_api.tf              # Função Lambda + package zip
│   ├── glue_etl.tf                # Glue Job ETL + upload de scripts no S3
│   ├── glue_details.tf            # Glue Job Details + upload de scripts no S3
│   ├── glue_agg.tf                # Glue Job AGG + upload de scripts no S3
│   ├── glue_data_quality.tf       # Glue Job Data Quality + upload de scripts
│   ├── glue_catalog.tf            # Database e tabelas no Glue Catalog
│   ├── lightsail_ia.tf            # Instância Lightsail + IAM user filmbot-agent
│   ├── eventbridge_lambda_api.tf  # Regra EventBridge que aciona a Lambda
│   ├── sns_topics.tf              # Tópicos SNS + subscrições de e-mail
│   ├── cloudwatch_alarms.tf       # Alarmes Lambda e EventBridge
│   ├── cloudwatch_glue_alarms.tf  # Alarmes Glue ETL e Data Quality
│   ├── cloudwatch_logs.tf         # Log groups
│   └── destroy_config.json        # Flag de destroy por ambiente: {"dev": false, "prod": false}
├── scripts/
│   └── backfill_traducao.py       # Adiciona title_pt/overview_pt a dados históricos no S3 SOT
└── test/
    ├── conftest.py                 # Fixtures globais
    ├── lambda_api/
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── test_main.py
    │   └── test_utils.py
    ├── glue_etl/
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── test_main.py
    │   └── test_utils.py
    ├── glue_data_quality/
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   ├── test_rulesets_dq.py
    │   └── test_utils.py
    ├── glue_details/
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   └── test_utils.py
    ├── glue_agg/
    │   ├── conftest.py
    │   ├── requirements_tests.txt
    │   └── test_utils.py
    └── lightsail/
        ├── conftest.py             # Setup de env vars (não tem fixtures)
        ├── requirements_tests.txt
        └── test_agent.py           # Testes do agente de recomendação
```

---

## GitHub Actions — Workflows

### `00_pipeline.yml` — Orquestrador principal

**Gatilhos:** push em `feature/*`, `develop`, `main` e `workflow_dispatch` (manual com input de ambiente).

**Fluxo de jobs:**

```
push em feature/*  →  test  →  auto-pr-feature (feature/* → develop)
push em develop    →  test  →  terraform (dev)   →  auto-pr-environment (develop → main)
push em main       →  test  →  terraform (prod)
workflow_dispatch  →  test  →  terraform (env escolhido manualmente)
```

**Secrets usados por ambiente:**
| Secret | dev | prod |
|--------|-----|------|
| `AWS_ASSUME_ROLE_ARN` | `_DEV` | `_PROD` |
| `AWS_STATEFILE_S3_BUCKET` | `_DEV` | `_PROD` |
| `AWS_LOCK_DYNAMODB_TABLE` | `_DEV` | `_PROD` |

---

### `01_test.yml` — Quality Gates (reutilizável)

Chamado por `00_pipeline.yml` em todas as branches. Roda em `ubuntu-latest`.

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
10. **pytest** — testes com cobertura; **quality gate: ≥ 70% de cobertura** (bloqueia se falhar)

---

### `02_terraform.yml` — Deploy de Infraestrutura (reutilizável)

**Inputs:** `environment` (dev | prod)  
**Secrets:** `aws-assume-role-arn`, `aws-statefile-s3-bucket`, `aws-lock-dynamodb-table`

**Etapas:**
1. Checkout + Setup Terraform 1.8.3
2. Autenticação AWS via **OIDC** (sem Access Keys fixas)
3. Lê `infra/destroy_config.json` para decidir destroy ou apply
4. `terraform init` com backend S3 dinâmico (bucket + key + região + DynamoDB lock)
5. `terraform validate`
6. **TFLint** — boas práticas Terraform (informativo)
7. **terraform fmt -check** (informativo)
8. **Checkov** — security/compliance scan (informativo)
9. Se `destroy_config[env] == true` → `terraform destroy`
10. Se não → `terraform plan -out=<env>.plan` → `terraform apply <env>.plan`

**Isolamento entre ambientes:** buckets S3 de state separados por ambiente (sem workspaces Terraform).

---

### `03_pr_auto.yml` — Auto Pull Request (reutilizável)

**Input:** `branch_name`

**Lógica de promoção:**
- `feature/*` → abre/atualiza PR para `develop`
- `develop` → abre/atualiza PR para `main`

Valida `terraform validate` (sem backend) antes de criar o PR.

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
| `s3.tf` | 6 buckets: SOR, SOT, SPEC, DQ, AUX (código), TEMP (Athena) |
| `iam_roles.tf` | Role para Lambda, Role para Glue |
| `iam_policies.tf` | Policies de mínimo privilégio por serviço |
| `lambda_api.tf` | Lambda function + zip do pacote Python |
| `glue_etl.tf` | Glue Job ETL + upload de scripts/dependências no S3 AUX |
| `glue_data_quality.tf` | Glue Job DQ + upload de scripts no S3 AUX |
| `glue_catalog.tf` | Database `db_tmdb` + todas as tabelas no Glue Catalog |
| `eventbridge_lambda_api.tf` | Regra de schedule EventBridge → Lambda |
| `sns_topics.tf` | Tópicos SNS + subscrições de e-mail para alertas |
| `cloudwatch_alarms.tf` | Alarmes Lambda e EventBridge (falha/sucesso) |
| `cloudwatch_glue_alarms.tf` | Alarmes Glue ETL e Glue DQ (falha/sucesso) |
| `cloudwatch_logs.tf` | Log groups de cada serviço |

### Controle de Destroy

Para destruir a infra de um ambiente, edite `infra/destroy_config.json`:
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
| `glue_agg` | `awswrangler`, `boto3`, `pandas`, `deep-translator`, `awsglue` (Glue runtime) |
| `lightsail_ia` | `streamlit`, `litellm`, `boto3`, `python-dotenv` |

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

O pipeline bloqueia se a cobertura de `app/` for **menor que 70%**.  
Rodar localmente: `pytest --cov=app --cov-report=term-missing --cov-fail-under=70`
